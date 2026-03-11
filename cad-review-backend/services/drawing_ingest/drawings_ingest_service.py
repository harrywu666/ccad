"""PDF 图纸上传与目录匹配入库。"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List

from fastapi import HTTPException, UploadFile

from domain.match_scoring import pick_catalog_candidate
from models import Catalog, Drawing
from services.cache_service import increment_cache_version, recalculate_project_status
from services.storage_path_service import resolve_project_dir

logger = logging.getLogger(__name__)

MAX_PDF_SIZE_BYTES = 500 * 1024 * 1024


def _safe_filename(raw: str) -> str:
    """提取纯文件名，防止路径穿越攻击。"""
    return PurePosixPath(raw).name or "upload"


def _render_pdf_page(pdf_path: str, page_index: int, dpi: int = 300) -> bytes:
    """线程中渲染单页PDF，避免阻塞事件循环。"""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


async def ingest_drawings_upload(project_id: str, project, file: UploadFile, db, set_progress) -> Dict[str, Any]:  # noqa: ANN001
    t0 = time.monotonic()
    logger.info("上传图纸开始: project_id=%s file=%s", project_id, file.filename)
    set_progress(project_id, "uploading", 2, "接收上传文件中")

    project_dir = resolve_project_dir(project, ensure=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    old_drawings = db.query(Drawing).filter(
        Drawing.project_id == project_id,
        Drawing.replaced_at == None,
    ).all()

    current_version = 1
    for drawing in old_drawings:
        drawing.replaced_at = datetime.now()
        current_version = max(current_version, drawing.data_version + 1)

    pdf_dir = project_dir / "pngs" / f"v{current_version}"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = pdf_dir / _safe_filename(file.filename or "upload.pdf")
    content = await file.read()
    if len(content) > MAX_PDF_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="PDF 文件不能超过 500MB")
    with open(pdf_path, "wb") as stream:
        stream.write(content)
    set_progress(project_id, "processing", 10, "文件上传完成，读取页数中")

    from services.kimi_service import async_recognize_sheet_info

    import fitz

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    logger.info("PDF读取完成: pages=%s path=%s", total_pages, str(pdf_path))
    set_progress(project_id, "processing", 12, f"共 {total_pages} 页，开始图像提取")

    matched_count = 0
    unmatched_count = 0

    catalog_items = db.query(Catalog).filter(
        Catalog.project_id == project_id,
        Catalog.status == "locked",
    ).all()
    catalog_dict = {item.sheet_no: item for item in catalog_items if item.sheet_no}

    page_assets: List[Dict[str, Any]] = []

    try:
        recognize_concurrency = int(os.getenv("KIMI_PAGE_CONCURRENCY", "20"))
    except ValueError:
        recognize_concurrency = 20
    recognize_concurrency = max(1, min(recognize_concurrency, 20))
    semaphore = asyncio.Semaphore(recognize_concurrency)
    logger.info("识别并发配置: KIMI_PAGE_CONCURRENCY=%s", recognize_concurrency)

    async def recognize_page(page_idx: int, png_bytes: bytes) -> Dict[str, Any]:
        async with semaphore:
            return await async_recognize_sheet_info(png_bytes, page_index=page_idx)

    tasks: List[asyncio.Task] = []
    for page_index in range(total_pages):
        png_data = await asyncio.to_thread(_render_pdf_page, str(pdf_path), page_index, 300)

        png_filename = f"page_{page_index + 1}.png"
        png_path = pdf_dir / png_filename
        with open(png_path, "wb") as stream:
            stream.write(png_data)

        page_assets.append(
            {
                "page_index": page_index,
                "png_path": str(png_path),
            }
        )
        logger.info("页 %s/%s: PNG已生成并提交识别 -> %s", page_index + 1, total_pages, str(png_path))
        tasks.append(asyncio.create_task(recognize_page(page_index, png_data)))
        submit_progress = 12 + int(((page_index + 1) / max(total_pages, 1)) * 28)
        set_progress(project_id, "processing", submit_progress, f"图像提取与识别排队 {page_index + 1}/{total_pages}")
    t_raster_done = time.monotonic()
    logger.info("流式转PNG与任务提交完成: pages=%s 耗时=%.2fs", total_pages, t_raster_done - t0)

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    set_progress(project_id, "processing", 70, "图像识别完成，开始目录匹配")
    t_recognize_done = time.monotonic()
    logger.info("单Agent识别阶段完成: pages=%s 耗时=%.2fs", total_pages, t_recognize_done - t_raster_done)
    page_results: List[Dict[str, Any]] = []

    for idx, result in enumerate(raw_results):
        if isinstance(result, Exception):
            logger.warning("第 %s 页识别失败: %s", idx + 1, str(result))
            page_results.append({"page_index": idx, "图号": "", "图名": "", "置信度": 0.0, "依据": str(result)})
            continue

        confidence_raw = result.get("置信度", 0.0)
        try:
            confidence = float(confidence_raw or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        page_results.append(
            {
                "page_index": idx,
                "图号": str(result.get("图号", "")).strip(),
                "图名": str(result.get("图名", "")).strip(),
                "置信度": confidence,
                "依据": str(result.get("依据", "")).strip(),
            }
        )
        logger.info(
            "页 %s: 单Agent结果 图号='%s' 图名='%s' 置信度=%.3f",
            idx + 1,
            page_results[-1]["图号"],
            page_results[-1]["图名"],
            page_results[-1]["置信度"],
        )

    t_match_start = time.monotonic()
    logger.info("算法匹配阶段开始: pages=%s catalog=%s", len(page_results), len(catalog_items))

    used_catalog_ids = set()

    for page in page_assets:
        page_index = page["page_index"]
        summary = page_results[page_index]

        sheet_no = summary["图号"]
        sheet_name = summary["图名"]

        matched_catalog = None
        match_score = 0.0
        no_score = 0.0
        name_score = 0.0

        if sheet_no and sheet_no in catalog_dict:
            candidate = catalog_dict[sheet_no]
            if candidate.id not in used_catalog_ids:
                matched_catalog = candidate
                match_score = 1.0
                no_score = 1.0

        if not matched_catalog:
            match_result = pick_catalog_candidate(
                recognized_no=sheet_no,
                recognized_name=sheet_name,
                catalogs=catalog_items,
                used_catalog_ids=used_catalog_ids,
            )
            matched_catalog = match_result["item"]
            match_score = float(match_result["score"])
            no_score = float(match_result["no_score"])
            name_score = float(match_result["name_score"])

        if matched_catalog:
            if matched_catalog.sheet_no:
                sheet_no = matched_catalog.sheet_no
            if matched_catalog.sheet_name and not sheet_name:
                sheet_name = matched_catalog.sheet_name

        if matched_catalog:
            used_catalog_ids.add(matched_catalog.id)
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
            png_path=page["png_path"],
            page_index=page_index,
            data_version=current_version,
            status=status,
        )
        db.add(drawing)
        logger.info(
            "页 %s: 落库 status=%s 图号='%s' 图名='%s' catalog_id=%s match=%.3f(no=%.3f,name=%.3f)",
            page_index + 1,
            status,
            sheet_no,
            sheet_name,
            matched_catalog.id if matched_catalog else "",
            match_score,
            no_score,
            name_score,
        )
        done_count = matched_count + unmatched_count
        match_progress = 70 + int((done_count / max(total_pages, 1)) * 24)
        set_progress(project_id, "processing", match_progress, f"目录匹配中 {done_count}/{total_pages}")

    t_match_done = time.monotonic()
    logger.info("算法匹配阶段完成: matched=%s unmatched=%s 耗时=%.2fs", matched_count, unmatched_count, t_match_done - t_match_start)

    recalculate_project_status(project_id, db)
    db.commit()
    set_progress(project_id, "processing", 97, "写入数据库完成，刷新缓存中")
    increment_cache_version(project_id, db)

    t_done = time.monotonic()
    logger.info(
        "上传图纸完成: project_id=%s total=%s matched=%s unmatched=%s version=%s 总耗时=%.2fs",
        project_id,
        total_pages,
        matched_count,
        unmatched_count,
        current_version,
        t_done - t0,
    )
    set_progress(project_id, "done", 100, "处理完成", success=True)

    return {
        "success": True,
        "total": total_pages,
        "matched": matched_count,
        "unmatched": unmatched_count,
        "version": current_version,
    }
