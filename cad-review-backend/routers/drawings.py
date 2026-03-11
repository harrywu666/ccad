"""
图纸管理路由
提供PDF上传、PNG转换、图名图号识别、匹配接口
"""

import json
import logging
import time
from threading import Lock
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from database import get_db
from models import Project, Catalog, Drawing, DrawingAnnotation
from services.storage_path_service import resolve_project_dir

router = APIRouter()
logger = logging.getLogger(__name__)
_DRAWINGS_UPLOAD_PROGRESS: Dict[str, Dict[str, Any]] = {}
_DRAWINGS_PROGRESS_LOCK = Lock()
_PROGRESS_TTL_SECONDS = 600


def _set_drawings_upload_progress(project_id: str, phase: str, progress: int, message: str, success: Optional[bool] = None):
    payload: Dict[str, Any] = {
        "phase": phase,
        "progress": max(0, min(100, int(progress))),
        "message": message,
        "updated_at": datetime.now().isoformat(),
        "_ts": time.monotonic(),
    }
    if success is not None:
        payload["success"] = success
    with _DRAWINGS_PROGRESS_LOCK:
        _DRAWINGS_UPLOAD_PROGRESS[project_id] = payload
        stale = [k for k, v in _DRAWINGS_UPLOAD_PROGRESS.items()
                 if time.monotonic() - v.get("_ts", 0) > _PROGRESS_TTL_SECONDS and k != project_id]
        for k in stale:
            del _DRAWINGS_UPLOAD_PROGRESS[k]


@router.get("/projects/{project_id}/drawings/upload-progress")
def get_drawings_upload_progress(project_id: str):
    with _DRAWINGS_PROGRESS_LOCK:
        payload = _DRAWINGS_UPLOAD_PROGRESS.get(project_id)
    if payload:
        return payload
    return {"phase": "idle", "progress": 0, "message": "等待上传", "updated_at": datetime.now().isoformat()}


class DrawingResponse(BaseModel):
    """图纸响应模型"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    catalog_id: Optional[str] = None
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None
    png_path: Optional[str] = None
    page_index: Optional[int] = None
    data_version: int
    status: str

class DrawingUpdateRequest(BaseModel):
    """图纸匹配更新请求"""
    catalog_id: Optional[str] = None
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None


class DrawingBatchDeleteRequest(BaseModel):
    drawing_ids: List[str]


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

    drawing = _get_drawing(project_id, drawing_id, db, allow_replaced=True)
    if not drawing or not drawing.png_path:
        raise HTTPException(status_code=404, detail="图纸PNG不存在")

    png_path = Path(drawing.png_path).expanduser()
    if not png_path.exists():
        raise HTTPException(status_code=404, detail="图纸PNG文件不存在")

    project_root = resolve_project_dir(project, ensure=False).resolve()
    resolved_png = png_path.resolve()
    try:
        resolved_png.relative_to(project_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="非法文件访问")

    return FileResponse(str(resolved_png), media_type="image/png")


@router.post("/projects/{project_id}/drawings/upload")
async def upload_drawings(project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传PDF图纸并处理（委托给 drawings_ingest_service）。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        _set_drawings_upload_progress(project_id, "failed", 0, "项目不存在", success=False)
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.drawing_ingest.drawings_ingest_service import ingest_drawings_upload

    try:
        result = await ingest_drawings_upload(
            project_id=project_id,
            project=project,
            file=file,
            db=db,
            set_progress=_set_drawings_upload_progress,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        _set_drawings_upload_progress(project_id, "failed", 0, str(exc), success=False)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/projects/{project_id}/drawings/upload-png")
async def upload_drawings_png(
    project_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """上传批量 PNG 图纸并处理。"""
    from services.drawing_ingest.png_ingest_service import ingest_png_upload

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        _set_drawings_upload_progress(project_id, "failed", 0, "项目不存在", success=False)
        raise HTTPException(status_code=404, detail="项目不存在")

    try:
        result = await ingest_png_upload(
            project_id=project_id,
            project=project,
            files=files,
            db=db,
            set_progress=_set_drawings_upload_progress,
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        _set_drawings_upload_progress(project_id, "failed", 0, str(exc), success=False)
        raise HTTPException(status_code=500, detail=str(exc))


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


@router.delete("/projects/{project_id}/drawings/{drawing_id}")
def delete_drawing(project_id: str, drawing_id: str, db: Session = Depends(get_db)):
    """删除单张图纸（逻辑删除）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    drawing = db.query(Drawing).filter(
        Drawing.id == drawing_id,
        Drawing.project_id == project_id,
        Drawing.replaced_at == None
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="图纸不存在")

    drawing.replaced_at = datetime.now()

    from services.cache_service import recalculate_project_status
    recalculate_project_status(project_id, db)
    db.commit()

    from services.cache_service import increment_cache_version
    increment_cache_version(project_id, db)

    return {"success": True}


@router.post("/projects/{project_id}/drawings/batch-delete")
def batch_delete_drawings(project_id: str, request: DrawingBatchDeleteRequest, db: Session = Depends(get_db)):
    """批量删除图纸（逻辑删除）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    ids = [str(i).strip() for i in request.drawing_ids if str(i).strip()]
    if not ids:
        return {"success": True, "deleted": 0}

    drawings = db.query(Drawing).filter(
        Drawing.project_id == project_id,
        Drawing.id.in_(ids),
        Drawing.replaced_at == None
    ).all()

    for drawing in drawings:
        drawing.replaced_at = datetime.now()

    from services.cache_service import recalculate_project_status
    recalculate_project_status(project_id, db)
    db.commit()

    from services.cache_service import increment_cache_version
    increment_cache_version(project_id, db)

    return {"success": True, "deleted": len(drawings)}


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


# ---------------------------------------------------------------------------
# 图纸标注 API
# ---------------------------------------------------------------------------

class AnnotationObjectIn(BaseModel):
    """单个标注对象"""
    type: Literal["stroke", "text"]
    color: Optional[str] = None
    stroke_width: Optional[int] = None
    path: Optional[str] = None
    text: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    font_size: Optional[float] = None
    scale_x: Optional[float] = None
    scale_y: Optional[float] = None


class AnnotationBoardIn(BaseModel):
    """标注画板请求体"""
    drawing_data_version: int
    schema_version: int
    objects: List[AnnotationObjectIn]


def _get_drawing(project_id: str, drawing_id: str, db: Session, *, allow_replaced: bool = False) -> Drawing:
    """获取图纸；allow_replaced=True 时允许访问历史版本图纸。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    query = db.query(Drawing).filter(
        Drawing.id == drawing_id,
        Drawing.project_id == project_id,
    )
    if not allow_replaced:
        query = query.filter(Drawing.replaced_at == None)
    drawing = query.first()
    if not drawing:
        raise HTTPException(status_code=404, detail="图纸不存在")
    return drawing


@router.get("/projects/{project_id}/annotations-by-sheet")
def get_annotations_by_sheet(
    project_id: str,
    sheet_no: str,
    audit_version: int,
    db: Session = Depends(get_db),
):
    """通过图号 + 审图版本查找标注（用于跨版本叠加显示）。

    同一图号在不同版本可能对应不同的 drawing_id（因重新上传），
    因此搜索范围包括已替换的旧图纸。
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    drawing_ids = [
        row[0] for row in
        db.query(Drawing.id)
        .filter(Drawing.project_id == project_id, Drawing.sheet_no == sheet_no)
        .all()
    ]

    if not drawing_ids:
        return {"schema_version": 1, "objects": [], "audit_version": audit_version}

    record = db.query(DrawingAnnotation).filter(
        DrawingAnnotation.drawing_id.in_(drawing_ids),
        DrawingAnnotation.project_id == project_id,
        DrawingAnnotation.audit_version == audit_version,
    ).first()

    if record and record.annotation_board:
        try:
            board = json.loads(record.annotation_board)
            board["audit_version"] = audit_version
            return board
        except (json.JSONDecodeError, TypeError):
            pass

    return {"schema_version": 1, "objects": [], "audit_version": audit_version}


@router.get("/projects/{project_id}/drawings/{drawing_id}/annotations")
def get_annotations(
    project_id: str,
    drawing_id: str,
    audit_version: int = Query(1),
    db: Session = Depends(get_db),
):
    """获取图纸标注画板（按审图版本隔离）。"""
    drawing = _get_drawing(project_id, drawing_id, db, allow_replaced=True)

    record = db.query(DrawingAnnotation).filter(
        DrawingAnnotation.drawing_id == drawing.id,
        DrawingAnnotation.project_id == project_id,
        DrawingAnnotation.audit_version == audit_version,
    ).first()

    if record and record.annotation_board:
        try:
            board = json.loads(record.annotation_board)
            board["drawing_id"] = drawing.id
            board["drawing_data_version"] = drawing.data_version
            return board
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "drawing_id": drawing.id,
        "drawing_data_version": drawing.data_version,
        "schema_version": 1,
        "objects": [],
    }


@router.put("/projects/{project_id}/drawings/{drawing_id}/annotations")
def put_annotations(
    project_id: str,
    drawing_id: str,
    audit_version: int = Query(1),
    payload: AnnotationBoardIn = Body(...),
    db: Session = Depends(get_db),
):
    """保存（覆盖）图纸标注画板（按审图版本隔离）。"""
    drawing = _get_drawing(project_id, drawing_id, db, allow_replaced=True)

    if payload.drawing_data_version != drawing.data_version:
        raise HTTPException(
            status_code=409,
            detail=f"图纸数据版本不匹配（期望 {drawing.data_version}，收到 {payload.drawing_data_version}）",
        )

    board_data = {
        "schema_version": payload.schema_version,
        "objects": [obj.model_dump(exclude_none=True) for obj in payload.objects],
    }
    board_json = json.dumps(board_data, ensure_ascii=False)

    record = db.query(DrawingAnnotation).filter(
        DrawingAnnotation.drawing_id == drawing.id,
        DrawingAnnotation.audit_version == audit_version,
    ).first()

    if record:
        record.annotation_board = board_json
        record.updated_at = datetime.now()
    else:
        import uuid
        record = DrawingAnnotation(
            id=str(uuid.uuid4()),
            drawing_id=drawing.id,
            project_id=project_id,
            audit_version=audit_version,
            annotation_board=board_json,
            updated_at=datetime.now(),
        )
        db.add(record)

    db.commit()
    return {"success": True}


@router.delete("/projects/{project_id}/drawings/{drawing_id}/annotations")
def delete_annotations(
    project_id: str,
    drawing_id: str,
    audit_version: int = Query(1),
    db: Session = Depends(get_db),
):
    """清空图纸标注（按审图版本隔离）。"""
    _get_drawing(project_id, drawing_id, db, allow_replaced=True)

    db.query(DrawingAnnotation).filter(
        DrawingAnnotation.drawing_id == drawing_id,
        DrawingAnnotation.project_id == project_id,
        DrawingAnnotation.audit_version == audit_version,
    ).delete()
    db.commit()
    return {"success": True}
