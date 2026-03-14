"""DWG 批量上传、提取、匹配、入库。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from fastapi import UploadFile

from domain.match_scoring import pick_catalog_candidate
from models import Catalog, JsonData
from services.cache_service import increment_cache_version, recalculate_project_status
from services.drawing_ingest.layout_units import expand_layout_json_units
from services.review_kernel.layout_contract import ensure_layout_json_contract
from services.storage_path_service import resolve_project_dir

logger = logging.getLogger(__name__)


def _cleanup_temp_files(dxf_dir: Path) -> None:
    """仅删除 DXF 临时目录，保留 DWG 原件用于后续质量回放与重建。"""
    # 删除持久化 DXF 目录（渲染缩略图后不再需要）
    if dxf_dir.exists():
        try:
            shutil.rmtree(dxf_dir)
            logger.info("已清理 DXF 目录: %s", dxf_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("清理 DXF 目录失败: %s (%s)", dxf_dir, exc)


def _safe_filename(raw: str) -> str:
    return PurePosixPath(raw).name or "upload"


async def ingest_dwg_upload(project_id: str, project, files: List[UploadFile], db, set_progress) -> Dict[str, Any]:  # noqa: ANN001
    project_dir = resolve_project_dir(project, ensure=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    dwg_dir = project_dir / "dwg"
    dwg_dir.mkdir(parents=True, exist_ok=True)

    json_dir = project_dir / "jsons"
    json_dir.mkdir(parents=True, exist_ok=True)

    catalog_items = (
        db.query(Catalog)
        .filter(
            Catalog.project_id == project_id,
            Catalog.status == "locked",
        )
        .order_by(Catalog.sort_order.asc())
        .all()
    )

    used_catalog_ids = set()
    results = []
    total_layouts = 0
    matched_layouts = 0
    unmatched_layouts = 0
    skipped_extra_layouts = 0
    placeholder_layouts = 0

    dwg_file_infos: List[Dict[str, str]] = []
    used_filenames: set[str] = set()
    for idx, file in enumerate(files):
        file_name = file.filename or ""
        if not file_name.lower().endswith(".dwg"):
            logger.warning("跳过非DWG文件: %s", file_name)
            continue

        safe_name = _safe_filename(file_name)
        if safe_name.lower() in used_filenames:
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix
            counter = 2
            while f"{stem}_{counter}{suffix}".lower() in used_filenames:
                counter += 1
            safe_name = f"{stem}_{counter}{suffix}"
        used_filenames.add(safe_name.lower())

        dwg_path = dwg_dir / safe_name
        with open(dwg_path, "wb") as stream:
            content = await file.read()
            stream.write(content)
        dwg_file_infos.append({"file_name": file_name, "path": str(dwg_path)})
        upload_progress = 4 + int(((idx + 1) / max(len(files), 1)) * 16)
        set_progress(project_id, "uploading", upload_progress, f"上传DWG文件 {idx + 1}/{len(files)}")

    if not dwg_file_infos:
        raise ValueError("未检测到有效DWG文件")

    from services.cad_service import extract_dwg_batch_data

    dxf_dir = project_dir / "dwg" / "dxf"
    dxf_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_dir = project_dir / "dwg" / "thumbnails"
    thumbnail_dir.mkdir(parents=True, exist_ok=True)

    set_progress(project_id, "processing", 22, "开始解析DWG布局")
    logger.info("批量DWG提取开始: files=%s", len(dwg_file_infos))
    extracted_by_file = await asyncio.to_thread(
        extract_dwg_batch_data,
        dwg_paths=[item["path"] for item in dwg_file_infos],
        output_dir=str(json_dir),
        dxf_dir=str(dxf_dir),
    )
    logger.info("批量DWG提取完成: files=%s", len(dwg_file_infos))
    set_progress(project_id, "processing", 45, "布局解析完成，开始目录匹配")

    expected_layouts = 0
    expanded_by_file: Dict[str, List[Dict[str, Any]]] = {}
    for item in dwg_file_infos:
        path_key = str(Path(item["path"]).resolve())
        units: List[Dict[str, Any]] = []
        for json_info in extracted_by_file.get(path_key, []):
            units.extend(expand_layout_json_units(json_info))
        expanded_by_file[path_key] = units
        expected_layouts += len(units)
    processed_layouts = 0

    for dwg_item in dwg_file_infos:
        file_name = dwg_item["file_name"]
        dwg_path = dwg_item["path"]

        logger.info("处理DWG提取结果: %s", str(dwg_path))
        layout_jsons = expanded_by_file.get(str(Path(dwg_path).resolve()), [])
        logger.info("DWG提取完成: file=%s layouts=%s", file_name, len(layout_jsons))

        for json_info in layout_jsons:
            total_layouts += 1
            processed_layouts += 1

            layout_name = str(json_info.get("layout_name", "")).strip()
            sheet_no = str(json_info.get("sheet_no", "")).strip()
            sheet_name = str(json_info.get("sheet_name", "")).strip()
            json_path = str(json_info.get("json_path", "")).strip()
            fragment_id = str(json_info.get("fragment_id", "")).strip()
            is_fragment_unit = bool(json_info.get("is_fragment_unit"))
            viewports = json_info.get("viewports", []) or []
            dimensions = json_info.get("dimensions", []) or []
            pseudo_texts = json_info.get("pseudo_texts", []) or []
            indexes = json_info.get("indexes", []) or []
            title_blocks = json_info.get("title_blocks", []) or []
            materials = json_info.get("materials", []) or []
            material_table = json_info.get("material_table", []) or []
            layers = json_info.get("layers", []) or []

            match_result = pick_catalog_candidate(
                recognized_no=sheet_no,
                recognized_name=sheet_name,
                layout_name=layout_name,
                catalogs=catalog_items,
                used_catalog_ids=used_catalog_ids,
                exact_sheet_no_first=True,
            )
            matched_catalog = match_result["item"]
            match_score = float(match_result["score"])
            no_score = float(match_result["no_score"])
            name_score = float(match_result["name_score"])

            if matched_catalog:
                used_catalog_ids.add(matched_catalog.id)
                matched_layouts += 1
                if matched_catalog.sheet_no:
                    sheet_no = matched_catalog.sheet_no
                if matched_catalog.sheet_name and not sheet_name:
                    sheet_name = matched_catalog.sheet_name
                status = "matched"
            else:
                unmatched_layouts += 1
                status = "unmatched"
                if catalog_items:
                    logger.info(
                        "未匹配布局(已保存): dwg=%s layout=%s sheet_no=%s",
                        file_name,
                        layout_name,
                        sheet_no,
                    )

            if matched_catalog:
                existing_versions = (
                    db.query(JsonData)
                    .filter(
                        JsonData.project_id == project_id,
                        JsonData.catalog_id == matched_catalog.id,
                    )
                    .all()
                )
            elif sheet_no:
                existing_versions = (
                    db.query(JsonData)
                    .filter(
                        JsonData.project_id == project_id,
                        JsonData.sheet_no == sheet_no,
                    )
                    .all()
                )
            else:
                existing_versions = []

            summary = (
                f"DWG:{file_name} 布局:{layout_name} "
                f"{f'分图:{fragment_id} ' if fragment_id else ''}"
                f"视口:{len(viewports)} 标注:{len(dimensions)} 伪标注:{len(pseudo_texts)} "
                f"索引:{len(indexes)} 标题栏:{len(title_blocks)} 材料:{len(materials)} "
                f"材料表:{len(material_table)} 图层:{len(layers)}"
            )
            normalized_base = re.sub(
                r'[\\/:*?"<>|]+',
                "_",
                f"{Path(file_name).stem}_{layout_name or sheet_no or 'layout'}_{fragment_id or 'layout'}",
            ).strip("_") or "layout"
            source_json_path = Path(json_path) if json_path and not is_fragment_unit else None
            versioned_json_path = json_dir / f"{normalized_base}_v1.json"

            next_version = 1
            for old in existing_versions:
                next_version = max(next_version, (old.data_version or 0) + 1)
                if old.is_latest == 1:
                    old.is_latest = 0

                versioned_json_path = json_dir / f"{normalized_base}_v{next_version}.json"

            compiled_payload: Dict[str, Any] | None = None
            ir_json_path = ""
            try:
                payload = json_info.get("data") or {}
                if payload:
                    payload = dict(payload)
                    if sheet_no:
                        payload["sheet_no"] = sheet_no
                    if sheet_name:
                        payload["sheet_name"] = sheet_name
                    if matched_catalog and matched_catalog.sheet_name:
                        payload["matched_catalog_sheet_name"] = matched_catalog.sheet_name
                if source_json_path and source_json_path.exists():
                    source_payload = json.loads(source_json_path.read_text(encoding="utf-8"))
                    if payload:
                        source_payload.update(payload)
                    source_payload, _, _ = ensure_layout_json_contract(source_payload)
                    compiled_payload = source_payload
                    versioned_json_path.write_text(
                        json.dumps(source_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                elif payload:
                    payload, _, _ = ensure_layout_json_contract(payload)
                    compiled_payload = payload
                    versioned_json_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                if versioned_json_path.exists():
                    json_path = str(versioned_json_path)

                if json_path and compiled_payload:
                    from services.review_kernel.ir_compiler import compile_layout_ir, persist_layout_ir

                    ir_package = compile_layout_ir(
                        compiled_payload,
                        source_json_path=json_path,
                        project_id=project_id,
                    )
                    ir_json_path = persist_layout_ir(ir_package, source_json_path=json_path)
                    summary = f"{summary} IR:{Path(ir_json_path).name}"
            except Exception as exc:  # noqa: BLE001
                logger.warning("JSON版本化落盘失败，保留原路径: %s (%s)", json_path, str(exc))

            # 只对未匹配布局按需渲染缩略图（已匹配的不需要）
            resolved_thumbnail = None
            if status == "unmatched":
                dxf_path_for_thumb = json_info.get("dxf_path")
                if dxf_path_for_thumb and Path(dxf_path_for_thumb).exists():
                    from services.dxf.pipeline import render_layout_thumbnail
                    thumb_filename = re.sub(r'[\\/:*?"<>|]+', "_", f"{Path(file_name).stem}_{layout_name}").strip("_") + ".png"
                    thumb_out = str(thumbnail_dir / thumb_filename)
                    resolved_thumbnail = render_layout_thumbnail(
                        __import__("ezdxf").readfile(dxf_path_for_thumb),
                        layout_name,
                        thumb_out,
                        dpi=96,
                    )

            new_json = JsonData(
                project_id=project_id,
                catalog_id=matched_catalog.id if matched_catalog else None,
                sheet_no=sheet_no or None,
                json_path=json_path or None,
                data_version=next_version,
                is_latest=1,
                summary=summary,
                status=status,
                thumbnail_path=resolved_thumbnail,
                layout_name=layout_name or None,
                source_dwg=file_name or None,
            )
            db.add(new_json)
            db.flush()

            logger.info(
                "布局落库: dwg=%s layout=%s sheet_no=%s status=%s v=%s match=%.3f(no=%.3f,name=%.3f)",
                file_name,
                layout_name,
                sheet_no,
                status,
                next_version,
                match_score,
                no_score,
                name_score,
            )

            results.append(
                {
                    "dwg": file_name,
                    "layout_name": layout_name,
                    "sheet_no": sheet_no,
                    "sheet_name": sheet_name,
                    "status": status,
                    "catalog_id": matched_catalog.id if matched_catalog else None,
                    "match_score": match_score,
                    "json_id": new_json.id,
                    "json_path": json_path,
                    "ir_json_path": ir_json_path or None,
                    "data_version": next_version,
                }
            )

            if expected_layouts > 0:
                process_progress = 45 + int((processed_layouts / expected_layouts) * 43)
                set_progress(project_id, "processing", process_progress, f"目录匹配与入库 {processed_layouts}/{expected_layouts}")

    if catalog_items:
        set_progress(project_id, "processing", 90, "补齐未匹配目录占位数据")
        for catalog_item in catalog_items:
            if catalog_item.id in used_catalog_ids:
                continue

            existing_versions = (
                db.query(JsonData)
                .filter(
                    JsonData.project_id == project_id,
                    JsonData.catalog_id == catalog_item.id,
                )
                .all()
            )

            next_version = 1
            for old in existing_versions:
                next_version = max(next_version, (old.data_version or 0) + 1)
                if old.is_latest == 1:
                    old.is_latest = 0

            base_name = re.sub(
                r'[\\/:*?"<>|]+',
                "_",
                f"placeholder_{catalog_item.sheet_no or catalog_item.sheet_name or catalog_item.id}",
            ).strip("_") or f"placeholder_{catalog_item.id}"
            placeholder_path = json_dir / f"{base_name}_v{next_version}.json"
            placeholder_payload = {
                "source_dwg": "",
                "layout_name": catalog_item.sheet_name or catalog_item.sheet_no or "未匹配图纸",
                "sheet_no": catalog_item.sheet_no or "",
                "sheet_name": catalog_item.sheet_name or "",
                "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_version": next_version,
                "scale": "",
                "model_range": {"min": [0.0, 0.0], "max": [0.0, 0.0]},
                "viewports": [],
                "dimensions": [],
                "pseudo_texts": [],
                "indexes": [],
                "title_blocks": [],
                "materials": [],
                "material_table": [],
                "layers": [],
                "is_placeholder": True,
            }
            placeholder_payload, _, _ = ensure_layout_json_contract(placeholder_payload)
            placeholder_path.write_text(
                json.dumps(placeholder_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            new_json = JsonData(
                project_id=project_id,
                catalog_id=catalog_item.id,
                sheet_no=catalog_item.sheet_no or None,
                json_path=str(placeholder_path),
                data_version=next_version,
                is_latest=1,
                summary=f"占位JSON: {catalog_item.sheet_no or ''} {catalog_item.sheet_name or ''}".strip(),
                status="unmatched",
            )
            db.add(new_json)
            db.flush()

            unmatched_layouts += 1
            placeholder_layouts += 1
            results.append(
                {
                    "dwg": "",
                    "layout_name": placeholder_payload["layout_name"],
                    "sheet_no": placeholder_payload["sheet_no"],
                    "sheet_name": placeholder_payload["sheet_name"],
                    "status": "unmatched",
                    "catalog_id": catalog_item.id,
                    "match_score": 0.0,
                    "json_id": new_json.id,
                    "json_path": str(placeholder_path),
                    "data_version": next_version,
                    "is_placeholder": True,
                }
            )

    set_progress(project_id, "processing", 96, "写入数据库并刷新缓存")
    recalculate_project_status(project_id, db)
    db.commit()

    # 清理临时文件：仅清理 DXF（中间产物），保留 DWG 原件用于可追溯重建
    _cleanup_temp_files(dxf_dir)

    increment_cache_version(project_id, db)
    set_progress(project_id, "done", 100, "处理完成", success=True)

    return {
        "success": True,
        "summary": {
            "dwg_files": len([f for f in files if (f.filename or "").lower().endswith(".dwg")]),
            "layouts_total": total_layouts,
            "matched": matched_layouts,
            "unmatched": unmatched_layouts,
            "skipped_extra_layouts": skipped_extra_layouts,
            "placeholder_layouts": placeholder_layouts,
        },
        "results": results,
    }
