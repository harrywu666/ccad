"""PNG 批量图纸上传与目录匹配入库。"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Callable, Dict, List

from fastapi import UploadFile

from domain.match_scoring import pick_catalog_candidate
from models import Catalog, Drawing
from services.cache_service import increment_cache_version, recalculate_project_status
from services.storage_path_service import resolve_project_dir

logger = logging.getLogger(__name__)


def _safe_filename(raw: str) -> str:
    """提取纯文件名，防止路径穿越攻击。"""
    return PurePosixPath(raw).name or "upload.png"


async def ingest_png_upload(
    project_id: str,
    project: Any,
    files: List[UploadFile],
    db: Any,
    set_progress: Callable[..., None],
) -> Dict[str, Any]:
    """处理批量 PNG 图纸上传。

    Args:
        project_id: 项目 ID。
        project: Project ORM 实例。
        files: 上传的 PNG 文件列表。
        db: SQLAlchemy Session。
        set_progress: 进度回调函数。

    Returns:
        包含 success / total / matched / unmatched / version 的结果字典。
    """
    t0 = time.monotonic()
    total_files = len(files)
    logger.info("批量PNG上传开始: project_id=%s files=%s", project_id, total_files)
    set_progress(project_id, "uploading", 2, f"接收 {total_files} 个PNG文件")

    project_dir = resolve_project_dir(project, ensure=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    old_drawings = db.query(Drawing).filter(
        Drawing.project_id == project_id,
        Drawing.replaced_at == None,  # noqa: E711
    ).all()

    current_version = 1
    for drawing in old_drawings:
        drawing.replaced_at = datetime.now()
        current_version = max(current_version, drawing.data_version + 1)

    png_dir = project_dir / "pngs" / f"v{current_version}"
    png_dir.mkdir(parents=True, exist_ok=True)

    page_assets: List[Dict[str, Any]] = []
    for idx, file in enumerate(files):
        content = await file.read()
        filename = _safe_filename(file.filename or f"page_{idx + 1}.png")
        png_path = png_dir / filename
        with open(png_path, "wb") as f:
            f.write(content)
        page_assets.append({
            "page_index": idx,
            "png_path": str(png_path),
            "png_bytes": content,
        })
        save_pct = 5 + int((idx + 1) / max(total_files, 1) * 15)
        set_progress(project_id, "processing", save_pct, f"保存文件 {idx + 1}/{total_files}")

    set_progress(project_id, "processing", 20, "文件保存完成，开始图号识别")

    from services.ai_service import async_recognize_sheet_info

    try:
        recognize_concurrency = int(os.getenv("KIMI_PAGE_CONCURRENCY", "20"))
    except ValueError:
        recognize_concurrency = 20
    recognize_concurrency = max(1, min(recognize_concurrency, 20))
    semaphore = asyncio.Semaphore(recognize_concurrency)

    async def recognize_page(page_idx: int, png_bytes: bytes) -> Dict[str, Any]:
        async with semaphore:
            return await async_recognize_sheet_info(png_bytes, page_index=page_idx)

    tasks = [
        asyncio.create_task(recognize_page(asset["page_index"], asset["png_bytes"]))
        for asset in page_assets
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    set_progress(project_id, "processing", 70, "图号识别完成，开始目录匹配")

    page_results: List[Dict[str, Any]] = []
    for idx, result in enumerate(raw_results):
        if isinstance(result, Exception):
            logger.warning("第 %s 个PNG识别失败: %s", idx + 1, str(result))
            page_results.append({"图号": "", "图名": "", "置信度": 0.0})
            continue
        page_results.append({
            "图号": str(result.get("图号", "")).strip(),
            "图名": str(result.get("图名", "")).strip(),
            "置信度": float(result.get("置信度", 0.0) or 0.0),
        })

    catalog_items = db.query(Catalog).filter(
        Catalog.project_id == project_id,
        Catalog.status == "locked",
    ).all()
    catalog_dict = {item.sheet_no: item for item in catalog_items if item.sheet_no}

    matched_count = 0
    unmatched_count = 0
    used_catalog_ids: set = set()

    for asset in page_assets:
        idx = asset["page_index"]
        summary = page_results[idx]
        sheet_no = summary["图号"]
        sheet_name = summary["图名"]

        matched_catalog = None
        if sheet_no and sheet_no in catalog_dict:
            candidate = catalog_dict[sheet_no]
            if candidate.id not in used_catalog_ids:
                matched_catalog = candidate

        if not matched_catalog:
            match_result = pick_catalog_candidate(
                recognized_no=sheet_no,
                recognized_name=sheet_name,
                catalogs=catalog_items,
                used_catalog_ids=used_catalog_ids,
            )
            matched_catalog = match_result["item"]

        if matched_catalog:
            used_catalog_ids.add(matched_catalog.id)
            if matched_catalog.sheet_no:
                sheet_no = matched_catalog.sheet_no
            if matched_catalog.sheet_name and not sheet_name:
                sheet_name = matched_catalog.sheet_name
            status = "matched"
            matched_count += 1
        else:
            status = "unmatched"
            unmatched_count += 1

        drawing = Drawing(
            project_id=project_id,
            catalog_id=matched_catalog.id if matched_catalog else None,
            sheet_no=sheet_no,
            sheet_name=sheet_name,
            png_path=asset["png_path"],
            page_index=idx,
            data_version=current_version,
            status=status,
        )
        db.add(drawing)

        done = matched_count + unmatched_count
        pct = 70 + int(done / max(total_files, 1) * 24)
        set_progress(project_id, "processing", pct, f"目录匹配 {done}/{total_files}")

    recalculate_project_status(project_id, db)
    db.commit()
    set_progress(project_id, "processing", 97, "写入完成，刷新缓存")
    increment_cache_version(project_id, db)

    t_done = time.monotonic()
    logger.info(
        "批量PNG上传完成: project_id=%s total=%s matched=%s unmatched=%s 耗时=%.2fs",
        project_id, total_files, matched_count, unmatched_count, t_done - t0,
    )
    set_progress(project_id, "done", 100, "处理完成", success=True)

    return {
        "success": True,
        "total": total_files,
        "matched": matched_count,
        "unmatched": unmatched_count,
        "version": current_version,
    }
