"""
误报反馈样本管理路由
提供样本列表查询、整理状态更新、JSONL 导出接口
"""

from typing import List, Literal, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
import json

from sqlalchemy import func
from database import get_db
from models import Project, FeedbackSample
from services.feedback_runtime_service import (
    refresh_runtime_feedback_index,
    update_feedback_sample_curation,
)

router = APIRouter()

CurationStatus = Literal["new", "accepted", "rejected"]


class FeedbackSampleResponse(BaseModel):
    """样本响应模型"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    audit_result_id: str
    audit_version: int
    issue_type: str
    severity: Optional[str] = None
    sheet_no_a: Optional[str] = None
    sheet_no_b: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    user_note: Optional[str] = None
    curation_status: str = "new"
    created_at: Optional[str] = None
    curated_at: Optional[str] = None

class CurationUpdateRequest(BaseModel):
    """整理状态更新"""
    curation_status: CurationStatus


class BatchCurationRequest(BaseModel):
    """批量整理"""
    sample_ids: List[str]
    curation_status: CurationStatus


@router.get("/projects/{project_id}/feedback-samples", response_model=List[FeedbackSampleResponse])
def list_feedback_samples(
    project_id: str,
    status: Optional[CurationStatus] = Query(None, description="按整理状态过滤"),
    issue_type: Optional[str] = Query(None, description="按问题类型过滤"),
    db: Session = Depends(get_db),
):
    """获取项目下的误报反馈样本列表"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    query = db.query(FeedbackSample).filter(FeedbackSample.project_id == project_id)
    if status:
        query = query.filter(FeedbackSample.curation_status == status)
    if issue_type:
        query = query.filter(FeedbackSample.issue_type == issue_type)

    samples = query.order_by(FeedbackSample.created_at.desc()).all()
    return [_serialize_sample(s) for s in samples]


@router.patch("/projects/{project_id}/feedback-samples/{sample_id}")
def update_sample_curation(
    project_id: str,
    sample_id: str,
    payload: CurationUpdateRequest,
    db: Session = Depends(get_db),
):
    """更新单个样本的整理状态"""
    sample = (
        db.query(FeedbackSample)
        .filter(FeedbackSample.project_id == project_id, FeedbackSample.id == sample_id)
        .first()
    )
    if not sample:
        raise HTTPException(status_code=404, detail="样本不存在")

    update_feedback_sample_curation(sample, payload.curation_status)
    db.commit()
    refresh_runtime_feedback_index(project_id=project_id, issue_type=sample.issue_type)
    return {"success": True}


@router.patch("/projects/{project_id}/feedback-samples/batch")
def batch_update_curation(
    project_id: str,
    payload: BatchCurationRequest,
    db: Session = Depends(get_db),
):
    """批量更新样本整理状态"""
    ids = list(dict.fromkeys(payload.sample_ids or []))
    if not ids:
        raise HTTPException(status_code=400, detail="sample_ids 不能为空")

    samples = (
        db.query(FeedbackSample)
        .filter(FeedbackSample.project_id == project_id, FeedbackSample.id.in_(ids))
        .all()
    )
    now = datetime.now()
    for s in samples:
        update_feedback_sample_curation(s, payload.curation_status)

    db.commit()
    for issue_type in {s.issue_type for s in samples if s.issue_type}:
        refresh_runtime_feedback_index(project_id=project_id, issue_type=issue_type)
    return {"success": True, "updated": len(samples)}


@router.get("/projects/{project_id}/feedback-samples/export")
def export_samples_jsonl(
    project_id: str,
    status: CurationStatus = Query("accepted", description="导出哪种状态的样本"),
    db: Session = Depends(get_db),
):
    """将样本导出为 JSONL 格式（逐行 JSON），用于训练/检索等下游消费"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    samples = (
        db.query(FeedbackSample)
        .filter(FeedbackSample.project_id == project_id, FeedbackSample.curation_status == status)
        .order_by(FeedbackSample.created_at.asc())
        .all()
    )

    def _generate():
        for s in samples:
            record = {
                "id": s.id,
                "project_id": s.project_id,
                "audit_result_id": s.audit_result_id,
                "audit_version": s.audit_version,
                "issue_type": s.issue_type,
                "severity": s.severity,
                "sheet_no_a": s.sheet_no_a,
                "sheet_no_b": s.sheet_no_b,
                "location": s.location,
                "description": s.description,
                "value_a": s.value_a,
                "value_b": s.value_b,
                "user_note": s.user_note,
                "snapshot": json.loads(s.snapshot_json) if s.snapshot_json else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            yield json.dumps(record, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _generate(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="feedback_samples_{project_id}_{status}.jsonl"'
        },
    )


@router.get("/feedback-samples/stats")
def global_feedback_stats(
    project_id: Optional[str] = Query(None, description="限定项目（不传则全局）"),
    db: Session = Depends(get_db),
):
    """全局（或指定项目）的样本状态统计"""
    query = db.query(
        FeedbackSample.curation_status,
        func.count(FeedbackSample.id),
    )
    if project_id:
        query = query.filter(FeedbackSample.project_id == project_id)
    rows = query.group_by(FeedbackSample.curation_status).all()

    counts = {"new": 0, "accepted": 0, "rejected": 0}
    for status_val, cnt in rows:
        key = status_val if status_val in counts else "new"
        counts[key] = cnt

    return {**counts, "total": sum(counts.values())}


@router.get("/feedback-samples/all")
def global_feedback_samples(
    project_id: Optional[str] = Query(None, description="限定项目"),
    status: Optional[CurationStatus] = Query(None, description="按整理状态过滤"),
    issue_type: Optional[str] = Query(None, description="按问题类型过滤"),
    db: Session = Depends(get_db),
):
    """跨项目的样本列表（附带项目名称）"""
    query = db.query(FeedbackSample, Project.name).join(
        Project, Project.id == FeedbackSample.project_id
    )
    if project_id:
        query = query.filter(FeedbackSample.project_id == project_id)
    if status:
        query = query.filter(FeedbackSample.curation_status == status)
    if issue_type:
        query = query.filter(FeedbackSample.issue_type == issue_type)

    rows = query.order_by(FeedbackSample.created_at.desc()).all()
    return [
        {**_serialize_sample(sample), "project_name": proj_name}
        for sample, proj_name in rows
    ]


@router.get("/feedback-samples/projects")
def projects_with_samples(db: Session = Depends(get_db)):
    """返回有误报样本的项目列表（供下拉选择器使用）"""
    rows = (
        db.query(Project.id, Project.name, func.count(FeedbackSample.id))
        .join(FeedbackSample, FeedbackSample.project_id == Project.id)
        .group_by(Project.id, Project.name)
        .order_by(Project.name)
        .all()
    )
    return [
        {"id": pid, "name": pname, "sample_count": cnt}
        for pid, pname, cnt in rows
    ]


def _serialize_sample(s: FeedbackSample) -> dict:
    """序列化单个样本"""
    return {
        "id": s.id,
        "project_id": s.project_id,
        "audit_result_id": s.audit_result_id,
        "audit_version": s.audit_version,
        "issue_type": s.issue_type,
        "severity": s.severity,
        "sheet_no_a": s.sheet_no_a,
        "sheet_no_b": s.sheet_no_b,
        "location": s.location,
        "description": s.description,
        "value_a": s.value_a,
        "value_b": s.value_b,
        "user_note": s.user_note,
        "curation_status": s.curation_status or "new",
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "curated_at": s.curated_at.isoformat() if s.curated_at else None,
    }
