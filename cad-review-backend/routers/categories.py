"""
分类管理路由
提供项目分类的CRUD接口
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from database import get_db
from models import ProjectCategory

router = APIRouter()


class CategoryResponse(BaseModel):
    """分类响应模型"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    color: str
    sort_order: int


class CategoryCreate(BaseModel):
    """分类创建模型"""
    name: str
    color: str = "#6B7280"


class CategoryUpdate(BaseModel):
    """分类更新模型"""
    name: Optional[str] = None
    color: Optional[str] = None


@router.get("/categories", response_model=List[CategoryResponse])
def get_categories(db: Session = Depends(get_db)):
    """获取所有分类"""
    return db.query(ProjectCategory).order_by(ProjectCategory.sort_order).all()


@router.post("/categories", response_model=CategoryResponse)
def create_category(category: CategoryCreate, db: Session = Depends(get_db)):
    """创建新分类"""
    existing = db.query(ProjectCategory).filter(ProjectCategory.name == category.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"分类名称 '{category.name}' 已存在")
    db_category = ProjectCategory(
        id=f"cat_{uuid.uuid4().hex[:12]}",
        name=category.name,
        color=category.color
    )
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category


@router.put("/categories/{category_id}", response_model=CategoryResponse)
def update_category(category_id: str, category: CategoryUpdate, db: Session = Depends(get_db)):
    """更新分类"""
    db_category = db.query(ProjectCategory).filter(ProjectCategory.id == category_id).first()
    if not db_category:
        raise HTTPException(status_code=404, detail="分类不存在")
    
    if category.name is not None:
        db_category.name = category.name
    if category.color is not None:
        db_category.color = category.color
    
    db.commit()
    db.refresh(db_category)
    return db_category


@router.delete("/categories/{category_id}")
def delete_category(category_id: str, db: Session = Depends(get_db)):
    """删除分类"""
    db_category = db.query(ProjectCategory).filter(ProjectCategory.id == category_id).first()
    if not db_category:
        raise HTTPException(status_code=404, detail="分类不存在")
    
    from models import Project
    projects_with_category = db.query(Project).filter(Project.category == category_id).all()
    for project in projects_with_category:
        project.category = None
    
    db.delete(db_category)
    db.commit()
    return {"success": True, "message": "分类已删除"}
