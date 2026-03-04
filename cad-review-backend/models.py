"""
数据库模型定义
包含所有数据表的ORM模型：projects, project_categories, catalog, drawings, json_data, audit_results
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


def generate_uuid():
    """生成UUID"""
    return str(uuid.uuid4())


class ProjectCategory(Base):
    """项目分类表"""
    __tablename__ = "project_categories"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, unique=True)
    color = Column(String, default="#6B7280")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class Project(Base):
    """项目表"""
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    category = Column(String, ForeignKey("project_categories.id"), nullable=True)
    tags = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    cache_version = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    status = Column(String, default="new")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    categories = relationship("ProjectCategory", foreign_keys=[category])
    catalogs = relationship("Catalog", back_populates="project", cascade="all, delete-orphan")
    drawings = relationship("Drawing", back_populates="project", cascade="all, delete-orphan")
    json_data_list = relationship("JsonData", back_populates="project", cascade="all, delete-orphan")
    audit_results = relationship("AuditResult", back_populates="project", cascade="all, delete-orphan")


class Catalog(Base):
    """图纸目录表"""
    __tablename__ = "catalog"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    sheet_no = Column(String, nullable=True)
    sheet_name = Column(String, nullable=True)
    version = Column(String, nullable=True)
    date = Column(String, nullable=True)
    status = Column(String, default="pending")
    sort_order = Column(Integer, default=0)

    project = relationship("Project", back_populates="catalogs")


class Drawing(Base):
    """图纸PNG表"""
    __tablename__ = "drawings"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    catalog_id = Column(String, ForeignKey("catalog.id"), nullable=True)
    sheet_no = Column(String, nullable=True)
    sheet_name = Column(String, nullable=True)
    png_path = Column(String, nullable=True)
    page_index = Column(Integer, nullable=True)
    data_version = Column(Integer, default=1)
    replaced_at = Column(DateTime, nullable=True)
    status = Column(String, default="unmatched")

    project = relationship("Project", back_populates="drawings")


class JsonData(Base):
    """DWG提取的JSON数据表"""
    __tablename__ = "json_data"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    catalog_id = Column(String, ForeignKey("catalog.id"), nullable=True)
    sheet_no = Column(String, nullable=True)
    json_path = Column(String, nullable=True)
    data_version = Column(Integer, default=1)
    is_latest = Column(Integer, default=1)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    status = Column(String, default="pending")

    project = relationship("Project", back_populates="json_data_list")


class AuditResult(Base):
    """审核结果表"""
    __tablename__ = "audit_results"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_version = Column(Integer, default=1)
    type = Column(String, nullable=True)
    severity = Column(String, default="error")
    sheet_no_a = Column(String, nullable=True)
    sheet_no_b = Column(String, nullable=True)
    location = Column(String, nullable=True)
    value_a = Column(String, nullable=True)
    value_b = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    project = relationship("Project", back_populates="audit_results")
