"""
数据库模型定义
包含所有数据表的ORM模型：projects, project_categories, catalog, drawings, json_data, audit_results, audit_runs
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Float, UniqueConstraint
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
    ui_preferences = Column(Text, nullable=True)
    cache_version = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    status = Column(String, default="new")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    categories = relationship("ProjectCategory", foreign_keys=[category])
    catalogs = relationship("Catalog", back_populates="project", cascade="all, delete-orphan")
    drawings = relationship("Drawing", back_populates="project", cascade="all, delete-orphan")
    json_data_list = relationship("JsonData", back_populates="project", cascade="all, delete-orphan")
    audit_results = relationship("AuditResult", back_populates="project", cascade="all, delete-orphan")
    audit_runs = relationship("AuditRun", back_populates="project", cascade="all, delete-orphan")
    sheet_contexts = relationship("SheetContext", back_populates="project", cascade="all, delete-orphan")
    sheet_edges = relationship("SheetEdge", back_populates="project", cascade="all, delete-orphan")
    audit_tasks = relationship("AuditTask", back_populates="project", cascade="all, delete-orphan")


class AIPromptSetting(Base):
    """全局 AI 提示词覆盖配置表"""
    __tablename__ = "ai_prompt_settings"

    stage_key = Column(String, primary_key=True)
    system_prompt_override = Column(Text, nullable=True)
    user_prompt_override = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


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
    annotation_board = Column(Text, nullable=True)

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
    evidence_json = Column(Text, nullable=True)
    is_resolved = Column(Integer, default=0)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    project = relationship("Project", back_populates="audit_results")


class AuditRun(Base):
    """审核任务运行记录表（用于异步进度和历史）"""
    __tablename__ = "audit_runs"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_version = Column(Integer, default=1)
    status = Column(String, default="running")
    current_step = Column(String, nullable=True)
    progress = Column(Integer, default=0)
    total_issues = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="audit_runs")


class SheetContext(Base):
    """图纸上下文分层表（L0/L1/L2）"""
    __tablename__ = "sheet_contexts"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    catalog_id = Column(String, ForeignKey("catalog.id"), nullable=True)
    sheet_no = Column(String, nullable=True)
    sheet_name = Column(String, nullable=True)
    status = Column(String, default="pending")
    layer_l0 = Column(Text, nullable=True)
    layer_l1 = Column(Text, nullable=True)
    layer_l2_json_path = Column(String, nullable=True)
    layer_l2_pdf_path = Column(String, nullable=True)
    layer_l2_page_index = Column(Integer, nullable=True)
    semantic_hash = Column(String, nullable=True)
    meta_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="sheet_contexts")


class SheetEdge(Base):
    """图纸关系边表（索引引用等）"""
    __tablename__ = "sheet_edges"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    source_sheet_no = Column(String, nullable=False)
    target_sheet_no = Column(String, nullable=False)
    edge_type = Column(String, default="index_ref")
    confidence = Column(Float, default=1.0)
    evidence_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="sheet_edges")


class DrawingAnnotation(Base):
    """图纸标注表（按审图版本隔离）"""
    __tablename__ = "drawing_annotations"

    id = Column(String, primary_key=True, default=generate_uuid)
    drawing_id = Column(String, ForeignKey("drawings.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_version = Column(Integer, nullable=False)
    annotation_board = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("drawing_id", "audit_version", name="uq_drawing_audit_version"),
    )

    drawing = relationship("Drawing")
    project = relationship("Project")


class AuditTask(Base):
    """审核任务规划表"""
    __tablename__ = "audit_tasks"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_version = Column(Integer, default=1)
    task_type = Column(String, nullable=False)  # index/dimension/material
    source_sheet_no = Column(String, nullable=True)
    target_sheet_no = Column(String, nullable=True)
    priority = Column(Integer, default=3)  # 1最高，5最低
    status = Column(String, default="pending")  # pending/running/done/failed
    trace_json = Column(Text, nullable=True)
    result_ref = Column(String, nullable=True)  # 可关联audit_results.id或聚合标识
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="audit_tasks")
