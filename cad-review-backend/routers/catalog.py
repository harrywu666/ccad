"""
目录管理路由
提供图纸目录的上传、识别、编辑、锁定接口
"""

import os
import shutil
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models import Project, Catalog
from services.storage_path_service import resolve_project_dir

router = APIRouter()

class CatalogItemResponse(BaseModel):
    """目录条目响应模型"""
    id: str
    project_id: str
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None
    version: Optional[str] = None
    date: Optional[str] = None
    status: str
    sort_order: int

    class Config:
        from_attributes = True


class CatalogUpdateRequest(BaseModel):
    """目录更新请求模型"""
    items: List[dict]


@router.get("/projects/{project_id}/catalog", response_model=List[CatalogItemResponse])
def get_catalog(project_id: str, db: Session = Depends(get_db)):
    """获取项目目录"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    items = db.query(Catalog).filter(Catalog.project_id == project_id).order_by(Catalog.sort_order).all()
    return items


@router.post("/projects/{project_id}/catalog/upload")
async def upload_catalog(project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传目录PNG图片并识别"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    project_dir = resolve_project_dir(project, ensure=True) / "catalog"
    project_dir.mkdir(parents=True, exist_ok=True)
    
    old_catalog_items = db.query(Catalog).filter(Catalog.project_id == project_id).all()
    for item in old_catalog_items:
        db.delete(item)
    
    file_path = project_dir / file.filename
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    from services.kimi_service import async_recognize_catalog
    try:
        items = await async_recognize_catalog(str(file_path))
    except Exception as e:
        return {"success": False, "error": str(e), "items": []}
    
    normalized_items = []

    def pick(source: dict, keys: List[str]) -> str:
        for k in keys:
            v = source.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    for item in items:
        sheet_no = pick(item, ["图号", "图纸号", "sheet_no", "sheetNo", "Drawing No", "DrawingNo", "Dwg#", "Dwg"])
        sheet_name = pick(item, ["图名", "图纸名称", "sheet_name", "sheetName", "Drawing Name", "DrawingName"])
        version = pick(item, ["版本", "版次", "version", "Revision"])
        date = pick(item, ["日期", "date", "Date"])

        # 过滤掉空白行
        if not sheet_no and not sheet_name:
            continue

        normalized_items.append({
            "图号": sheet_no,
            "图名": sheet_name,
            "版本": version,
            "日期": date,
        })

    for idx, item in enumerate(normalized_items):
        catalog_item = Catalog(
            project_id=project_id,
            sheet_no=item.get("图号", ""),
            sheet_name=item.get("图名", ""),
            version=item.get("版本", ""),
            date=item.get("日期", ""),
            status="pending",
            sort_order=idx
        )
        db.add(catalog_item)
    
    db.commit()
    
    from services.cache_service import increment_cache_version
    increment_cache_version(project_id, db)
    
    return {"success": True, "items": normalized_items}


@router.put("/projects/{project_id}/catalog", response_model=List[CatalogItemResponse])
def update_catalog(project_id: str, request: CatalogUpdateRequest, db: Session = Depends(get_db)):
    """更新目录条目（用户校对）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    existing_items = db.query(Catalog).filter(Catalog.project_id == project_id).all()
    existing_map = {str(item.id): item for item in existing_items}

    has_locked_items = any(item.status == "locked" for item in existing_items)
    default_status = "locked" if has_locked_items else "pending"

    incoming_ids = set()
    for idx, item_data in enumerate(request.items):
        item_id = item_data.get("id")
        item_id = str(item_id) if item_id is not None else None
        if item_id and item_id in existing_map:
            catalog_item = existing_map[item_id]
            incoming_ids.add(item_id)
            catalog_item.sheet_no = item_data.get("sheet_no", "")
            catalog_item.sheet_name = item_data.get("sheet_name", "")
            catalog_item.version = item_data.get("version", "")
            catalog_item.date = item_data.get("date", "")
            catalog_item.sort_order = idx
        else:
            catalog_item = Catalog(
                project_id=project_id,
                sheet_no=item_data.get("sheet_no", ""),
                sheet_name=item_data.get("sheet_name", ""),
                version=item_data.get("version", ""),
                date=item_data.get("date", ""),
                status=default_status,
                sort_order=idx
            )
            db.add(catalog_item)

    for item in existing_items:
        if str(item.id) not in incoming_ids:
            db.delete(item)

    from services.cache_service import recalculate_project_status, increment_cache_version
    recalculate_project_status(project_id, db)
    db.commit()
    increment_cache_version(project_id, db)

    items = db.query(Catalog).filter(Catalog.project_id == project_id).order_by(Catalog.sort_order).all()
    return items


@router.post("/projects/{project_id}/catalog/lock")
def lock_catalog(project_id: str, db: Session = Depends(get_db)):
    """锁定目录"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    items = db.query(Catalog).filter(Catalog.project_id == project_id).all()
    for item in items:
        item.status = "locked"
    
    from services.cache_service import recalculate_project_status
    recalculate_project_status(project_id, db)

    db.commit()
    
    from services.cache_service import increment_cache_version
    increment_cache_version(project_id, db)
    
    return {"success": True, "message": "目录已锁定"}


@router.delete("/projects/{project_id}/catalog")
def delete_catalog(project_id: str, db: Session = Depends(get_db)):
    """删除目录"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    items = db.query(Catalog).filter(Catalog.project_id == project_id).all()
    for item in items:
        db.delete(item)
    
    project_dir = resolve_project_dir(project, ensure=False) / "catalog"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    
    from services.cache_service import recalculate_project_status
    recalculate_project_status(project_id, db)
    
    db.commit()
    
    from services.cache_service import increment_cache_version
    increment_cache_version(project_id, db)
    
    return {"success": True, "message": "目录已删除"}
