"""
DWG管理路由
提供DWG上传、按布局拆分JSON、目录匹配、版本管理接口
"""

from __future__ import annotations

import logging
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from database import get_db
from models import JsonData, Project

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


class JsonDataResponse(BaseModel):
    """JSON数据响应模型"""
    model_config = ConfigDict(from_attributes=True)

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
        from services.drawing_ingest.dwg_ingest_service import ingest_dwg_upload

        return await ingest_dwg_upload(
            project_id=project_id,
            project=project,
            files=files,
            db=db,
            set_progress=_set_dwg_upload_progress,
        )
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
