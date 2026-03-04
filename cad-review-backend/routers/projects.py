"""
项目管理路由
提供项目的CRUD接口，包含分类筛选、搜索、缓存版本管理
"""

import os
import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models import Project, ProjectCategory

router = APIRouter()

BASE_DIR = Path.home() / "cad-review"
PROJECTS_DIR = BASE_DIR / "projects"


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
    
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "catalog").mkdir(exist_ok=True)
    (project_dir / "pngs").mkdir(exist_ok=True)
    (project_dir / "jsons").mkdir(exist_ok=True)
    (project_dir / "reports").mkdir(exist_ok=True)
    
    return db_project


@router.put("/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, project: ProjectUpdate, db: Session = Depends(get_db)):
    """更新项目信息"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
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
    return db_project


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    """删除项目"""
    db_project = db.query(Project).filter(Project.id == project_id).first()
    if not db_project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    project_dir = PROJECTS_DIR / project_id
    if project_dir.exists():
        import shutil
        shutil.rmtree(project_dir)
    
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
