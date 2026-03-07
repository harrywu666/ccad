"""
DWG管理路由
提供DWG上传、按布局拆分JSON、目录匹配、版本管理接口
"""

from __future__ import annotations

import json
import logging
import shutil
import re
from datetime import datetime
from threading import Lock
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Catalog, JsonData, Project
from services.storage_path_service import resolve_project_dir


def _safe_filename(raw: str) -> str:
    """提取纯文件名，防止路径穿越攻击。"""
    return PurePosixPath(raw).name or "upload"

router = APIRouter()
logger = logging.getLogger(__name__)
_DWG_UPLOAD_PROGRESS: Dict[str, Dict[str, Any]] = {}
_DWG_PROGRESS_LOCK = Lock()
_DWG_PROGRESS_TTL_SECONDS = 600


def _set_dwg_upload_progress(project_id: str, phase: str, progress: int, message: str, success: Optional[bool] = None):
    import time as _time
    payload: Dict[str, Any] = {
        "phase": phase,
        "progress": max(0, min(100, int(progress))),
        "message": message,
        "updated_at": datetime.now().isoformat(),
        "_ts": _time.monotonic(),
    }
    if success is not None:
        payload["success"] = success
    with _DWG_PROGRESS_LOCK:
        _DWG_UPLOAD_PROGRESS[project_id] = payload
        stale = [k for k, v in _DWG_UPLOAD_PROGRESS.items()
                 if _time.monotonic() - v.get("_ts", 0) > _DWG_PROGRESS_TTL_SECONDS and k != project_id]
        for k in stale:
            del _DWG_UPLOAD_PROGRESS[k]

def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    s = value.strip().lower()
    s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", s)
    return "".join(ch for ch in s if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"))


def _score_sheet_no(recognized: str, catalog: str) -> float:
    if not recognized or not catalog:
        return 0.0
    if recognized == catalog:
        return 1.0

    rn = _normalize_text(recognized)
    cn = _normalize_text(catalog)
    if not rn or not cn:
        return 0.0
    if rn == cn:
        return 0.99
    if rn in cn or cn in rn:
        return 0.94
    return SequenceMatcher(None, rn, cn).ratio() * 0.9


def _score_sheet_name(recognized: str, catalog: str) -> float:
    if not recognized or not catalog:
        return 0.0
    if recognized == catalog:
        return 1.0

    rn = _normalize_text(recognized)
    cn = _normalize_text(catalog)
    if not rn or not cn:
        return 0.0
    if rn == cn:
        return 0.98
    if rn in cn or cn in rn:
        return 0.92
    return SequenceMatcher(None, rn, cn).ratio() * 0.9


def _pick_catalog_item(
    sheet_no: str,
    sheet_name: str,
    layout_name: str,
    catalog_items: List[Catalog],
    used_catalog_ids: set,
) -> Dict[str, Any]:
    if sheet_no:
        for item in catalog_items:
            if item.id in used_catalog_ids:
                continue
            if (item.sheet_no or "").strip() == sheet_no.strip():
                return {"item": item, "score": 1.0, "no_score": 1.0, "name_score": 0.0}

    best_item = None
    best_score = 0.0
    best_no_score = 0.0
    best_name_score = 0.0

    for item in catalog_items:
        if item.id in used_catalog_ids:
            continue

        no_score = _score_sheet_no(sheet_no, item.sheet_no or "")
        name_score = max(
            _score_sheet_name(sheet_name, item.sheet_name or ""),
            _score_sheet_name(layout_name, item.sheet_name or ""),
        )

        if sheet_no:
            score = max(no_score, no_score * 0.85 + name_score * 0.25)
            if no_score < 0.60 and name_score >= 0.85:
                score = max(score, name_score * 0.90)
            if no_score >= 0.90 and name_score >= 0.70:
                score += 0.03
        else:
            score = name_score * 0.95

        if score > best_score:
            best_item = item
            best_score = score
            best_no_score = no_score
            best_name_score = name_score

    threshold = 0.72 if sheet_no else 0.78
    if not best_item or best_score < threshold:
        return {"item": None, "score": best_score, "no_score": best_no_score, "name_score": best_name_score}

    return {"item": best_item, "score": best_score, "no_score": best_no_score, "name_score": best_name_score}


class JsonDataResponse(BaseModel):
    """JSON数据响应模型"""

    id: str
    project_id: str
    catalog_id: Optional[str] = None
    sheet_no: Optional[str] = None
    json_path: Optional[str] = None
    data_version: int
    is_latest: int
    summary: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JsonBatchDeleteRequest(BaseModel):
    json_ids: List[str]


@router.get("/projects/{project_id}/dwg/upload-progress")
def get_dwg_upload_progress(project_id: str):
    with _DWG_PROGRESS_LOCK:
        payload = _DWG_UPLOAD_PROGRESS.get(project_id)
    if payload:
        return payload
    return {"phase": "idle", "progress": 0, "message": "等待上传", "updated_at": datetime.now().isoformat()}


@router.get("/projects/{project_id}/dwg", response_model=List[JsonDataResponse])
def get_json_data_list(project_id: str, db: Session = Depends(get_db)):
    """获取项目最新JSON数据列表"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    json_list = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .order_by(JsonData.sheet_no.asc(), JsonData.created_at.desc())
        .all()
    )
    return json_list


@router.get("/projects/{project_id}/dwg/{json_id}/history", response_model=List[JsonDataResponse])
def get_json_data_history(project_id: str, json_id: str, db: Session = Depends(get_db)):
    """查看某张图纸JSON历史版本"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    target = (
        db.query(JsonData)
        .filter(
            JsonData.id == json_id,
            JsonData.project_id == project_id,
        )
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="JSON数据不存在")

    filters = [JsonData.project_id == project_id]
    if target.catalog_id:
        filters.append(JsonData.catalog_id == target.catalog_id)
    elif target.sheet_no:
        filters.append(JsonData.sheet_no == target.sheet_no)
    else:
        filters.append(JsonData.id == target.id)

    history = (
        db.query(JsonData)
        .filter(*filters)
        .order_by(JsonData.data_version.desc(), JsonData.created_at.desc())
        .all()
    )
    return history


@router.post("/projects/{project_id}/dwg/upload")
async def upload_dwg(project_id: str, files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    """
    上传DWG并按布局生成JSON。
    核心规则：一个DWG可拆多个布局JSON；Model不计入图纸。
    """
    _set_dwg_upload_progress(project_id, "uploading", 2, "接收DWG文件中")
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        _set_dwg_upload_progress(project_id, "failed", 0, "项目不存在", success=False)
        raise HTTPException(status_code=404, detail="项目不存在")

    try:
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
        for idx, file in enumerate(files):
            file_name = file.filename or ""
            if not file_name.lower().endswith(".dwg"):
                logger.warning("跳过非DWG文件: %s", file_name)
                continue

            dwg_path = dwg_dir / _safe_filename(file_name)
            content = await file.read()
            if len(content) > 500 * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"DWG 文件 {file_name} 不能超过 500MB")
            with open(dwg_path, "wb") as f:
                f.write(content)
            dwg_file_infos.append({"file_name": file_name, "path": str(dwg_path)})
            upload_progress = 4 + int(((idx + 1) / max(len(files), 1)) * 16)
            _set_dwg_upload_progress(project_id, "uploading", upload_progress, f"上传DWG文件 {idx + 1}/{len(files)}")

        if not dwg_file_infos:
            _set_dwg_upload_progress(project_id, "failed", 0, "未检测到有效DWG文件", success=False)
            raise HTTPException(status_code=400, detail="未检测到有效DWG文件")

        from services.cad_service import extract_dwg_batch_data

        _set_dwg_upload_progress(project_id, "processing", 22, "开始解析DWG布局")
        logger.info("批量DWG提取开始: files=%s", len(dwg_file_infos))
        extracted_by_file = extract_dwg_batch_data(
            dwg_paths=[item["path"] for item in dwg_file_infos],
            output_dir=str(json_dir),
        )
        logger.info("批量DWG提取完成: files=%s", len(dwg_file_infos))
        _set_dwg_upload_progress(project_id, "processing", 45, "布局解析完成，开始目录匹配")

        expected_layouts = sum(
            len(extracted_by_file.get(str(Path(item["path"]).resolve()), []))
            for item in dwg_file_infos
        )
        processed_layouts = 0

        for dwg_item in dwg_file_infos:
            file_name = dwg_item["file_name"]
            dwg_path = dwg_item["path"]

            logger.info("处理DWG提取结果: %s", str(dwg_path))
            layout_jsons = extracted_by_file.get(str(Path(dwg_path).resolve()), [])
            logger.info("DWG提取完成: file=%s layouts=%s", file_name, len(layout_jsons))

            for json_info in layout_jsons:
                total_layouts += 1
                processed_layouts += 1

                layout_name = str(json_info.get("layout_name", "")).strip()
                sheet_no = str(json_info.get("sheet_no", "")).strip()
                sheet_name = str(json_info.get("sheet_name", "")).strip()
                json_path = str(json_info.get("json_path", "")).strip()
                viewports = json_info.get("viewports", []) or []
                dimensions = json_info.get("dimensions", []) or []
                pseudo_texts = json_info.get("pseudo_texts", []) or []
                indexes = json_info.get("indexes", []) or []
                title_blocks = json_info.get("title_blocks", []) or []
                materials = json_info.get("materials", []) or []
                material_table = json_info.get("material_table", []) or []
                layers = json_info.get("layers", []) or []

                match_result = _pick_catalog_item(
                    sheet_no=sheet_no,
                    sheet_name=sheet_name,
                    layout_name=layout_name,
                    catalog_items=catalog_items,
                    used_catalog_ids=used_catalog_ids,
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
                    # 目录已锁定时，按目录一对一约束：额外布局不入库
                    if catalog_items:
                        skipped_extra_layouts += 1
                        logger.info(
                            "跳过额外布局(未命中目录): dwg=%s layout=%s sheet_no=%s",
                            file_name,
                            layout_name,
                            sheet_no,
                        )
                        continue

                    unmatched_layouts += 1
                    status = "unmatched"

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

                next_version = 1
                for old in existing_versions:
                    next_version = max(next_version, (old.data_version or 0) + 1)
                    if old.is_latest == 1:
                        old.is_latest = 0

                summary = (
                    f"DWG:{file_name} 布局:{layout_name} "
                    f"视口:{len(viewports)} 标注:{len(dimensions)} 伪标注:{len(pseudo_texts)} "
                    f"索引:{len(indexes)} 标题栏:{len(title_blocks)} 材料:{len(materials)} "
                    f"材料表:{len(material_table)} 图层:{len(layers)}"
                )

                # 版本化存储：{dwg}_{layout}_v{n}.json，保留历史文件
                normalized_base = re.sub(
                    r'[\\/:*?"<>|]+',
                    "_",
                    f"{Path(file_name).stem}_{layout_name or sheet_no or 'layout'}",
                ).strip("_") or "layout"
                versioned_json_path = json_dir / f"{normalized_base}_v{next_version}.json"
                source_json_path = Path(json_path) if json_path else None

                try:
                    if source_json_path and source_json_path.exists():
                        if source_json_path.resolve() != versioned_json_path.resolve():
                            shutil.copy2(source_json_path, versioned_json_path)
                        else:
                            # 已是目标路径，保持不动
                            pass
                    else:
                        payload = json_info.get("data") or {}
                        if payload:
                            versioned_json_path.write_text(
                                json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8",
                            )
                    if versioned_json_path.exists():
                        json_path = str(versioned_json_path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("JSON版本化落盘失败，保留原路径: %s (%s)", json_path, str(exc))

                new_json = JsonData(
                    project_id=project_id,
                    catalog_id=matched_catalog.id if matched_catalog else None,
                    sheet_no=sheet_no or None,
                    json_path=json_path or None,
                    data_version=next_version,
                    is_latest=1,
                    summary=summary,
                    status=status,
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
                        "data_version": next_version,
                    }
                )

                if expected_layouts > 0:
                    process_progress = 45 + int((processed_layouts / expected_layouts) * 43)
                    _set_dwg_upload_progress(project_id, "processing", process_progress, f"目录匹配与入库 {processed_layouts}/{expected_layouts}")

        # 目录锁定后，若存在未匹配目录项，补占位JSON，保证一对一
        if catalog_items:
            _set_dwg_upload_progress(project_id, "processing", 90, "补齐未匹配目录占位数据")
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

        from services.cache_service import recalculate_project_status

        _set_dwg_upload_progress(project_id, "processing", 96, "写入数据库并刷新缓存")
        recalculate_project_status(project_id, db)
        db.commit()

        from services.cache_service import increment_cache_version

        increment_cache_version(project_id, db)
        _set_dwg_upload_progress(project_id, "done", 100, "处理完成", success=True)

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
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("DWG上传处理失败: project_id=%s", project_id)
        _set_dwg_upload_progress(project_id, "failed", 0, f"处理失败: {str(exc)}", success=False)
        raise


@router.delete("/projects/{project_id}/dwg/{json_id}")
def delete_json_data(project_id: str, json_id: str, db: Session = Depends(get_db)):
    """删除某条JSON（逻辑删除：is_latest=0）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    json_data = (
        db.query(JsonData)
        .filter(
            JsonData.id == json_id,
            JsonData.project_id == project_id,
        )
        .first()
    )
    if not json_data:
        raise HTTPException(status_code=404, detail="JSON数据不存在")

    json_data.is_latest = 0

    from services.cache_service import recalculate_project_status

    recalculate_project_status(project_id, db)
    db.commit()

    from services.cache_service import increment_cache_version

    increment_cache_version(project_id, db)
    return {"success": True}


@router.post("/projects/{project_id}/dwg/batch-delete")
def batch_delete_json_data(project_id: str, request: JsonBatchDeleteRequest, db: Session = Depends(get_db)):
    """批量删除JSON（逻辑删除：is_latest=0）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    ids = [str(i).strip() for i in request.json_ids if str(i).strip()]
    if not ids:
        return {"success": True, "deleted": 0}

    rows = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.id.in_(ids),
            JsonData.is_latest == 1,
        )
        .all()
    )
    for row in rows:
        row.is_latest = 0

    from services.cache_service import recalculate_project_status
    recalculate_project_status(project_id, db)
    db.commit()

    from services.cache_service import increment_cache_version
    increment_cache_version(project_id, db)
    return {"success": True, "deleted": len(rows)}
