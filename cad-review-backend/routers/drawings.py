"""
图纸管理路由
提供PDF上传、PNG转换、图名图号识别、匹配接口
"""

import os
import asyncio
import logging
import time
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models import Project, Catalog, Drawing

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR = Path.home() / "cad-review"


def _render_pdf_page(pdf_path: str, page_index: int, dpi: int = 300) -> bytes:
    """线程中渲染单页PDF，避免阻塞事件循环"""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png")
    finally:
        doc.close()


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    s = value.strip().lower()
    s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：]+", "", s)
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


def _pick_catalog_by_algorithm(
    recognized_no: str,
    recognized_name: str,
    catalogs: List[Catalog],
    used_catalog_ids: set,
) -> Dict[str, Any]:
    best_item = None
    best_score = 0.0
    best_no_score = 0.0
    best_name_score = 0.0

    for item in catalogs:
        if item.id in used_catalog_ids:
            continue

        no_score = _score_sheet_no(recognized_no, item.sheet_no or "")
        name_score = _score_sheet_name(recognized_name, item.sheet_name or "")

        if recognized_no:
            score = max(no_score, no_score * 0.85 + name_score * 0.25)
            # 图号明显异常时，允许按图名强匹配兜底
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

    if not best_item:
        return {"item": None, "score": 0.0, "no_score": 0.0, "name_score": 0.0}

    threshold = 0.72 if recognized_no else 0.78
    if best_score < threshold:
        return {"item": None, "score": best_score, "no_score": best_no_score, "name_score": best_name_score}

    return {"item": best_item, "score": best_score, "no_score": best_no_score, "name_score": best_name_score}


class DrawingResponse(BaseModel):
    """图纸响应模型"""
    id: str
    project_id: str
    catalog_id: Optional[str] = None
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None
    png_path: Optional[str] = None
    page_index: Optional[int] = None
    data_version: int
    status: str

    class Config:
        from_attributes = True


class DrawingUpdateRequest(BaseModel):
    """图纸匹配更新请求"""
    catalog_id: Optional[str] = None
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None


@router.get("/projects/{project_id}/drawings", response_model=List[DrawingResponse])
def get_drawings(project_id: str, db: Session = Depends(get_db)):
    """获取项目图纸列表"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    drawings = db.query(Drawing).filter(
        Drawing.project_id == project_id,
        Drawing.replaced_at == None
    ).order_by(Drawing.page_index).all()
    
    return drawings


@router.get("/projects/{project_id}/drawings/{drawing_id}/image")
def get_drawing_image(project_id: str, drawing_id: str, db: Session = Depends(get_db)):
    """获取图纸PNG缩略图源文件"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    drawing = db.query(Drawing).filter(
        Drawing.id == drawing_id,
        Drawing.project_id == project_id,
        Drawing.replaced_at == None
    ).first()
    if not drawing or not drawing.png_path:
        raise HTTPException(status_code=404, detail="图纸PNG不存在")

    png_path = Path(drawing.png_path).expanduser()
    if not png_path.exists():
        raise HTTPException(status_code=404, detail="图纸PNG文件不存在")

    project_root = (BASE_DIR / "projects" / project_id).resolve()
    resolved_png = png_path.resolve()
    try:
        resolved_png.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="非法文件访问")

    return FileResponse(str(resolved_png), media_type="image/png")


@router.post("/projects/{project_id}/drawings/upload")
async def upload_drawings(project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传PDF图纸并处理"""
    t0 = time.monotonic()
    logger.info("上传图纸开始: project_id=%s file=%s", project_id, file.filename)
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    project_dir = BASE_DIR / "projects" / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    
    old_drawings = db.query(Drawing).filter(
        Drawing.project_id == project_id,
        Drawing.replaced_at == None
    ).all()
    
    current_version = 1
    for drawing in old_drawings:
        drawing.replaced_at = datetime.now()
        current_version = max(current_version, drawing.data_version + 1)
    
    pdf_dir = project_dir / "pngs" / f"v{current_version}"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_path = pdf_dir / file.filename
    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    from services.kimi_service import (
        async_recognize_sheet_info,
    )

    import fitz
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    logger.info("PDF读取完成: pages=%s path=%s", total_pages, str(pdf_path))

    matched_count = 0
    unmatched_count = 0

    catalog_items = db.query(Catalog).filter(
        Catalog.project_id == project_id,
        Catalog.status == "locked"
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
        # 单页渲染放在线程中执行，使已提交的识别任务可并行推进
        png_data = await asyncio.to_thread(_render_pdf_page, str(pdf_path), page_index, 300)

        png_filename = f"page_{page_index + 1}.png"
        png_path = pdf_dir / png_filename
        with open(png_path, "wb") as f:
            f.write(png_data)

        page_assets.append(
            {
                "page_index": page_index,
                "png_path": str(png_path),
            }
        )
        logger.info("页 %s/%s: PNG已生成并提交识别 -> %s", page_index + 1, total_pages, str(png_path))
        tasks.append(asyncio.create_task(recognize_page(page_index, png_data)))
    t_raster_done = time.monotonic()
    logger.info("流式转PNG与任务提交完成: pages=%s 耗时=%.2fs", total_pages, t_raster_done - t0)

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
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
            match_result = _pick_catalog_by_algorithm(
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
            # 匹配成功后以目录值为准，保证后续DWG/审核流程稳定
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

    t_match_done = time.monotonic()
    logger.info("算法匹配阶段完成: matched=%s unmatched=%s 耗时=%.2fs", matched_count, unmatched_count, t_match_done - t_match_start)
    
    from services.cache_service import recalculate_project_status
    recalculate_project_status(project_id, db)
    
    db.commit()
    
    from services.cache_service import increment_cache_version
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
    
    return {
        "success": True,
        "total": total_pages,
        "matched": matched_count,
        "unmatched": unmatched_count,
        "version": current_version
    }


@router.put("/projects/{project_id}/drawings/{drawing_id}")
def update_drawing(
    project_id: str,
    drawing_id: str,
    request: Optional[DrawingUpdateRequest] = Body(default=None),
    catalog_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """更新图纸匹配关系"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    drawing = db.query(Drawing).filter(
        Drawing.id == drawing_id,
        Drawing.project_id == project_id
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="图纸不存在")
    
    selected_catalog_id = request.catalog_id if request and request.catalog_id else catalog_id

    if selected_catalog_id:
        catalog = db.query(Catalog).filter(
            Catalog.id == selected_catalog_id,
            Catalog.project_id == project_id
        ).first()
        if catalog:
            drawing.catalog_id = selected_catalog_id
            drawing.sheet_no = catalog.sheet_no
            drawing.sheet_name = catalog.sheet_name
            drawing.status = "matched"
    elif request:
        if request.sheet_no is not None:
            drawing.sheet_no = request.sheet_no.strip()
        if request.sheet_name is not None:
            drawing.sheet_name = request.sheet_name.strip()
        drawing.status = "matched" if drawing.catalog_id else "unmatched"

    from services.cache_service import recalculate_project_status
    recalculate_project_status(project_id, db)
    
    db.commit()
    
    from services.cache_service import increment_cache_version
    increment_cache_version(project_id, db)
    
    return {"success": True}


@router.delete("/projects/{project_id}/drawings")
def delete_drawings(project_id: str, db: Session = Depends(get_db)):
    """删除所有图纸"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    drawings = db.query(Drawing).filter(Drawing.project_id == project_id).all()
    for drawing in drawings:
        drawing.replaced_at = datetime.now()
    
    from services.cache_service import recalculate_project_status
    recalculate_project_status(project_id, db)
    
    db.commit()
    
    from services.cache_service import increment_cache_version
    increment_cache_version(project_id, db)
    
    return {"success": True, "message": "图纸已删除"}
