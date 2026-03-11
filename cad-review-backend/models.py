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
    audit_events = relationship("AuditRunEvent", back_populates="project", cascade="all, delete-orphan")
    sheet_contexts = relationship("SheetContext", back_populates="project", cascade="all, delete-orphan")
    sheet_edges = relationship("SheetEdge", back_populates="project", cascade="all, delete-orphan")
    audit_tasks = relationship("AuditTask", back_populates="project", cascade="all, delete-orphan")
    feedback_samples = relationship("FeedbackSample", back_populates="project", cascade="all, delete-orphan")
    feedback_threads = relationship("FeedbackThread", back_populates="project", cascade="all, delete-orphan")
    feedback_message_attachments = relationship("FeedbackMessageAttachment", back_populates="project", cascade="all, delete-orphan")
    feedback_learning_records = relationship("FeedbackLearningRecord", back_populates="project", cascade="all, delete-orphan")
    layout_registrations = relationship("DrawingLayoutRegistration", back_populates="project", cascade="all, delete-orphan")
    project_memory_records = relationship("ProjectMemoryRecord", back_populates="project", cascade="all, delete-orphan")


class AIPromptSetting(Base):
    """全局 AI 提示词覆盖配置表"""
    __tablename__ = "ai_prompt_settings"

    stage_key = Column(String, primary_key=True)
    system_prompt_override = Column(Text, nullable=True)
    user_prompt_override = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AuditSkillEntry(Base):
    """全局审查技能包规则表"""
    __tablename__ = "audit_skill_entries"

    id = Column(String, primary_key=True, default=generate_uuid)
    skill_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String, default="manual")
    execution_mode = Column(String, default="ai")
    stage_keys = Column(Text, nullable=True)
    source_sample_ids = Column(Text, nullable=True)
    is_active = Column(Integer, default=1)
    priority = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.now)
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
    thumbnail_path = Column(String, nullable=True)
    layout_name = Column(String, nullable=True)
    source_dwg = Column(String, nullable=True)

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
    rule_id = Column(String, nullable=True)
    finding_type = Column(String, nullable=True)
    finding_status = Column(String, nullable=True)
    source_agent = Column(String, nullable=True)
    evidence_pack_id = Column(String, nullable=True)
    review_round = Column(Integer, default=1)
    triggered_by = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)
    is_resolved = Column(Integer, default=0)
    resolved_at = Column(DateTime, nullable=True)
    feedback_status = Column(String, default="none")
    feedback_at = Column(DateTime, nullable=True)
    feedback_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    project = relationship("Project", back_populates="audit_results")
    feedback_threads = relationship("FeedbackThread", back_populates="audit_result", cascade="all, delete-orphan")
    feedback_learning_records = relationship("FeedbackLearningRecord", back_populates="audit_result", cascade="all, delete-orphan")


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
    provider_mode = Column(String, nullable=True)
    scope_mode = Column(String, default="full")
    scope_summary = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="audit_runs")


class ProjectMemoryRecord(Base):
    """主审运行记忆表"""
    __tablename__ = "project_memory_records"
    __table_args__ = (
        UniqueConstraint("project_id", "audit_version", name="uq_project_memory_project_version"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_version = Column(Integer, default=1, nullable=False)
    memory_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    project = relationship("Project", back_populates="project_memory_records")


class AuditRunEvent(Base):
    """审图运行事件表（用于进度日志面板）"""
    __tablename__ = "audit_run_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_version = Column(Integer, default=1)
    level = Column(String, default="info")
    step_key = Column(String, nullable=True)
    agent_key = Column(String, nullable=True)
    agent_name = Column(String, nullable=True)
    event_kind = Column(String, nullable=True)
    progress_hint = Column(Integer, nullable=True)
    message = Column(Text, nullable=False)
    meta_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    project = relationship("Project", back_populates="audit_events")


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


class AuditIssueDrawing(Base):
    """审核问题与具体图纸定位记录表"""
    __tablename__ = "audit_issue_drawings"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_result_id = Column(String, ForeignKey("audit_results.id"), nullable=False)
    audit_version = Column(Integer, nullable=False)
    match_side = Column(String, nullable=False)  # source/target
    drawing_id = Column(String, ForeignKey("drawings.id"), nullable=True)
    drawing_data_version = Column(Integer, nullable=True)
    sheet_no = Column(String, nullable=True)
    sheet_name = Column(String, nullable=True)
    index_no = Column(String, nullable=True)
    anchor_json = Column(Text, nullable=True)
    match_status = Column(String, default="matched")  # matched/missing_drawing/missing_anchor
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("audit_result_id", "match_side", name="uq_audit_issue_result_side"),
    )

    project = relationship("Project")
    audit_result = relationship("AuditResult")
    drawing = relationship("Drawing")


class DrawingLayoutRegistration(Base):
    """DWG layout 与 PDF 页面坐标配准记录表"""
    __tablename__ = "drawing_layout_registrations"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    drawing_id = Column(String, ForeignKey("drawings.id"), nullable=False)
    drawing_data_version = Column(Integer, nullable=True)
    sheet_no = Column(String, nullable=True)
    layout_name = Column(String, nullable=False)
    pdf_page_index = Column(Integer, nullable=True)
    layout_page_range_json = Column(Text, nullable=True)
    pdf_page_size_json = Column(Text, nullable=True)
    transform_json = Column(Text, nullable=True)
    registration_method = Column(String, default="layout_page_direct")
    registration_confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("drawing_id", "layout_name", "pdf_page_index", name="uq_drawing_layout_pdf_page"),
    )

    project = relationship("Project", back_populates="layout_registrations")
    drawing = relationship("Drawing")


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


class FeedbackSample(Base):
    """误报反馈样本表——独立于 AuditResult 的训练数据存储层"""
    __tablename__ = "feedback_samples"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_result_id = Column(String, nullable=False)
    audit_version = Column(Integer, nullable=False)
    issue_type = Column(String, nullable=False)
    severity = Column(String, nullable=True)
    sheet_no_a = Column(String, nullable=True)
    sheet_no_b = Column(String, nullable=True)
    location = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)
    value_a = Column(String, nullable=True)
    value_b = Column(String, nullable=True)
    user_note = Column(Text, nullable=True)
    snapshot_json = Column(Text, nullable=True)
    curation_status = Column(String, default="new")
    created_at = Column(DateTime, default=datetime.now)
    curated_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="feedback_samples")


class FeedbackThread(Base):
    """误报反馈会话表。"""
    __tablename__ = "feedback_threads"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_result_id = Column(String, ForeignKey("audit_results.id"), nullable=False)
    result_group_id = Column(String, nullable=True)
    audit_version = Column(Integer, nullable=False, default=1)
    status = Column(String, default="open")
    learning_decision = Column(String, default="pending")
    agent_decision = Column(String, nullable=True)
    agent_confidence = Column(Float, nullable=True)
    opened_by = Column(String, nullable=True)
    source_agent = Column(String, nullable=True)
    rule_id = Column(String, nullable=True)
    issue_type = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    resolution_reason = Column(Text, nullable=True)
    escalation_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    closed_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="feedback_threads")
    audit_result = relationship("AuditResult", back_populates="feedback_threads")
    messages = relationship("FeedbackMessage", back_populates="thread", cascade="all, delete-orphan")
    learning_records = relationship("FeedbackLearningRecord", back_populates="thread", cascade="all, delete-orphan")


class FeedbackMessage(Base):
    """误报反馈会话消息表。"""
    __tablename__ = "feedback_messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    thread_id = Column(String, ForeignKey("feedback_threads.id"), nullable=False)
    role = Column(String, nullable=False)
    message_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    structured_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    thread = relationship("FeedbackThread", back_populates="messages")
    attachments = relationship("FeedbackMessageAttachment", back_populates="message", cascade="all, delete-orphan")


class FeedbackMessageAttachment(Base):
    """误报反馈消息图片附件表。"""
    __tablename__ = "feedback_message_attachments"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    thread_id = Column(String, ForeignKey("feedback_threads.id"), nullable=False)
    message_id = Column(String, ForeignKey("feedback_messages.id"), nullable=False)
    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    storage_path = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    project = relationship("Project", back_populates="feedback_message_attachments")
    thread = relationship("FeedbackThread")
    message = relationship("FeedbackMessage", back_populates="attachments")


class FeedbackLearningRecord(Base):
    """误报反馈学习门禁记录表。"""
    __tablename__ = "feedback_learning_records"

    id = Column(String, primary_key=True, default=generate_uuid)
    thread_id = Column(String, ForeignKey("feedback_threads.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    audit_result_id = Column(String, ForeignKey("audit_results.id"), nullable=False)
    rule_id = Column(String, nullable=True)
    issue_type = Column(String, nullable=True)
    decision = Column(String, default="pending")
    reason_code = Column(String, nullable=True)
    reason_text = Column(Text, nullable=True)
    evidence_score = Column(Float, nullable=True)
    similar_case_count = Column(Integer, nullable=True)
    reusability_score = Column(Float, nullable=True)
    suggested_intervention_level = Column(String, nullable=True)
    snapshot_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    thread = relationship("FeedbackThread", back_populates="learning_records")
    project = relationship("Project", back_populates="feedback_learning_records")
    audit_result = relationship("AuditResult", back_populates="feedback_learning_records")
