"""
项目管理路由
提供项目的CRUD接口，包含分类筛选、搜索、缓存版本管理
"""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models import Project, ProjectCategory
from services.storage_path_service import (
    ensure_project_scaffold,
    remove_project_dirs,
    rename_project_named_dir,
    resolve_project_dir,
)

router = APIRouter()

class ProjectResponse(BaseModel):
    """项目响应模型"""
    id: str
    name: str
    category: Optional[str] = None
    tags: Optional[str] = None
    description: Optional[str] = None
    cache_version: int
    created_at: datetime
    status: str
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    """项目创建模型"""
    name: str
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    """项目更新模型"""
    name: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None


class ProjectUIPreferencesUpdate(BaseModel):
    preferences: Dict[str, Any]


def _load_ui_preferences(db_project: Project) -> Dict[str, Any]:
    if not db_project.ui_preferences:
        return {}
    try:
        parsed = json.loads(db_project.ui_preferences)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _deep_merge_dict(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


@router.get("/projects", response_model=List[ProjectResponse])
def get_projects(
    category: Optional[str] = Query(None, description="按分类筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    search: Optional[str] = Query(None, description="项目名称搜索"),
    db: Session = Depends(get_db)
):
    """获取项目列表，支持分类、状态筛选和名称搜索"""
    query = db.query(Project)
    
    if category:
        query = query.filter(Project.category == category)
    if status:
        query = query.filter(Project.status == status)
    if search:
        query = query.filter(Project.name.contains(search))
    
    return query.order_by(Project.updated_at.desc()).all()


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, db: Session = Depends(get_db)):
    """获取单个项目详情"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.get("/projects/{project_id}/ui-preferences")
def get_project_ui_preferences(project_id: str, db: Session = Depends(get_db)):
    """获取项目级UI偏好配置"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"project_id": project_id, "preferences": _load_ui_preferences(project)}


@router.put("/projects/{project_id}/ui-preferences")
def update_project_ui_preferences(project_id: str, payload: ProjectUIPreferencesUpdate, db: Session = Depends(get_db)):
    """更新项目级UI偏好配置（增量合并）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    current = _load_ui_preferences(project)
    merged = _deep_merge_dict(current, payload.preferences or {})
    project.ui_preferences = json.dumps(merged, ensure_ascii=False)
    project.updated_at = datetime.now()
    db.commit()
    db.refresh(project)
    return {"project_id": project_id, "preferences": merged}


@router.post("/projects", response_model=ProjectResponse)
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    """创建新项目"""
    project_id = f"proj_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    while db.query(Project).filter(Project.id == project_id).first():
        project_id = f"proj_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    
    tags_json = json.dumps(project.tags) if project.tags else None
    
    db_project = Project(
        id=project_id,
        name=project.name,
        category=project.category,
        tags=tags_json,
        description=project.description,
        status="new"
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)

    project_dir = resolve_project_dir(db_project, ensure=True)
    ensure_project_scaffold(project_dir)
    
    return db_project


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, project: ProjectUpdate, db: Session = Depends(get_db)):
    """更新项目信息"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="项目不存在")
    old_name = db_project.name

    if project.name is not None:
        db_project.name = project.name
    if project.category is not None:
        db_project.category = project.category
    if project.tags is not None:
        db_project.tags = json.dumps(project.tags)
    if project.description is not None:
        db_project.description = project.description
    
    db_project.updated_at = datetime.now()
    db.commit()
    db.refresh(db_project)

    if project.name is not None and project.name != old_name:
        rename_project_named_dir(db_project, old_name=old_name, new_name=db_project.name)

    return db_project


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    """删除项目"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    remove_project_dirs(db_project)
    
    db.delete(db_project)
    db.commit()
    return {"success": True, "message": "项目已删除"}


@router.get("/projects/{project_id}/cache_version")
def get_cache_version(project_id: str, client_version: int = Query(0), db: Session = Depends(get_db)):
    """获取项目缓存版本，用于前端判断是否需要刷新"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    return {
        "cache_version": project.cache_version,
        "client_version": client_version,
        "needs_refresh": project.cache_version > client_version
    }
