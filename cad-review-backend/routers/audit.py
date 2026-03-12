"""
审核管理路由
提供审核启动、进度查询、结果查询接口
"""

from typing import Any, Dict, List, Literal, Optional
from datetime import datetime
import logging
import os
import threading
import time
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, ConfigDict
from database import get_db, SessionLocal
import json as _json
from models import (
    Project,
    AuditResult,
    AuditRun,
    AuditRunEvent,
    AuditTask,
    AuditIssueDrawing,
    DrawingAnnotation,
    FeedbackSample,
)
from services.audit.issue_preview import get_issue_preview
from services.audit_runtime.result_view import (
    group_results_for_view,
    normalize_feedback_status,
    serialize_audit_result,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_STOP_CLEANUP_LOCK = threading.Lock()
_STOP_CLEANUP_JOBS: set[tuple[str, int]] = set()

AuditFeedbackStatus = Literal["none", "incorrect"]


class AuditResultResponse(BaseModel):
    """审核结果响应模型"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    audit_version: int
    type: str
    severity: str
    sheet_no_a: Optional[str] = None
    sheet_no_b: Optional[str] = None
    location: Optional[str] = None
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    rule_id: Optional[str] = None
    finding_type: Optional[str] = None
    finding_status: Optional[str] = None
    source_agent: Optional[str] = None
    evidence_pack_id: Optional[str] = None
    review_round: int = 1
    triggered_by: Optional[str] = None
    confidence: Optional[float] = None
    description: Optional[str] = None
    evidence_json: Optional[str] = None
    locations: List[str] = []
    occurrence_count: int = 1
    is_resolved: bool = False
    resolved_at: Optional[datetime] = None
    feedback_status: AuditFeedbackStatus = "none"
    feedback_at: Optional[datetime] = None
    feedback_note: Optional[str] = None
    is_grouped: bool = False
    group_id: Optional[str] = None
    issue_ids: List[str] = []


class AuditStatusResponse(BaseModel):
    """审核状态响应模型"""

    project_id: str
    status: str
    audit_version: Optional[int] = None
    current_step: Optional[str] = None
    progress: int = 0
    total_issues: int = 0
    run_status: Optional[str] = None
    provider_mode: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    scope_mode: Optional[str] = None
    scope_summary: Optional[str] = None


class AuditResultUpdateRequest(BaseModel):
    is_resolved: Optional[bool] = None
    feedback_status: Optional[AuditFeedbackStatus] = None
    feedback_note: Optional[str] = None


class BatchAuditResultUpdateRequest(BaseModel):
    result_ids: List[str]
    is_resolved: Optional[bool] = None
    feedback_status: Optional[AuditFeedbackStatus] = None
    feedback_note: Optional[str] = None


class AuditTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    audit_version: int
    task_type: str
    source_sheet_no: Optional[str] = None
    target_sheet_no: Optional[str] = None
    priority: int
    status: str
    trace_json: Optional[str] = None
    result_ref: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AuditRunEventResponse(BaseModel):
    id: int
    audit_version: int
    level: str
    step_key: Optional[str] = None
    agent_key: Optional[str] = None
    agent_name: Optional[str] = None
    event_kind: Optional[str] = None
    progress_hint: Optional[int] = None
    message: str
    created_at: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class AuditRunEventListResponse(BaseModel):
    items: List[AuditRunEventResponse]
    next_since_id: Optional[int] = None


class ThreeLineSummaryResponse(BaseModel):
    total: int
    ready: int
    missing_png: int
    missing_json: int
    missing_all: int


class ThreeLineAssetResponse(BaseModel):
    id: str
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None
    data_version: Optional[int] = None
    status: Optional[str] = None
    png_path: Optional[str] = None
    page_index: Optional[int] = None
    json_path: Optional[str] = None
    summary: Optional[str] = None
    is_placeholder: Optional[bool] = None
    created_at: Optional[str] = None


class ThreeLineItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    catalog_id: str
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None
    sort_order: int
    status: str
    drawing: Optional[ThreeLineAssetResponse] = None
    json_data: Optional[ThreeLineAssetResponse] = Field(default=None, alias="json")


class UnmatchedJsonResponse(BaseModel):
    id: str
    sheet_no: Optional[str] = None
    layout_name: Optional[str] = None
    source_dwg: Optional[str] = None
    thumbnail_path: Optional[str] = None
    json_path: Optional[str] = None
    data_version: Optional[int] = None
    status: Optional[str] = None
    created_at: Optional[str] = None


class ThreeLineMatchResponse(BaseModel):
    project_id: str
    summary: ThreeLineSummaryResponse
    items: List[ThreeLineItemResponse]
    unmatched_jsons: List[UnmatchedJsonResponse] = []


class StartAuditRequest(BaseModel):
    allow_incomplete: bool = False
    provider_mode: Optional[str] = None


class AuditIssueDrawingPreviewAssetResponse(BaseModel):
    drawing_id: str
    drawing_data_version: Optional[int] = None
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None
    page_index: Optional[int] = None
    match_status: str
    anchor: Optional[Dict[str, Any]] = None
    layout_anchor: Optional[Dict[str, Any]] = None
    pdf_anchor: Optional[Dict[str, Any]] = None
    highlight_region: Optional[Dict[str, Any]] = None
    anchor_status: str = "missing"
    registration_confidence: Optional[float] = None
    index_no: Optional[str] = None


class AuditIssuePreviewIssueResponse(BaseModel):
    id: str
    audit_version: int
    type: Optional[str] = None
    severity: Optional[str] = None
    sheet_no_a: Optional[str] = None
    sheet_no_b: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None


class AuditIssuePreviewResponse(BaseModel):
    issue: AuditIssuePreviewIssueResponse
    source: Optional[AuditIssueDrawingPreviewAssetResponse] = None
    target: Optional[AuditIssueDrawingPreviewAssetResponse] = None
    missing_reason: Optional[str] = None


def _serialize_audit_result(item: AuditResult) -> Dict[str, Any]:
    return serialize_audit_result(item)


def _normalize_feedback_status(value: Optional[str]) -> AuditFeedbackStatus:
    return "incorrect" if normalize_feedback_status(value) == "incorrect" else "none"


def _ensure_update_payload(
    is_resolved: Optional[bool],
    feedback_status: Optional[AuditFeedbackStatus],
) -> None:
    if is_resolved is None and feedback_status is None:
        raise HTTPException(
            status_code=400, detail="至少提供 is_resolved 或 feedback_status"
        )


def _apply_audit_result_updates(
    item: AuditResult,
    *,
    is_resolved: Optional[bool],
    feedback_status: Optional[AuditFeedbackStatus],
    feedback_note: Optional[str] = None,
    updated_at: datetime,
) -> None:
    if is_resolved is not None:
        item.is_resolved = 1 if is_resolved else 0
        item.resolved_at = updated_at if is_resolved else None

    if feedback_status is not None:
        normalized_status = _normalize_feedback_status(feedback_status)
        item.feedback_status = normalized_status
        item.feedback_at = updated_at if normalized_status == "incorrect" else None
        item.feedback_note = feedback_note if normalized_status == "incorrect" else None


def _sync_feedback_samples(
    db: Session,
    items: List[AuditResult],
    feedback_status: Optional[AuditFeedbackStatus],
    feedback_note: Optional[str],
) -> None:
    """根据反馈状态同步 feedback_samples 表：标记 incorrect 时创建快照，撤销时删除。"""
    if feedback_status is None:
        return

    normalized = _normalize_feedback_status(feedback_status)
    for item in items:
        existing = (
            db.query(FeedbackSample)
            .filter(FeedbackSample.audit_result_id == item.id)
            .first()
        )
        if normalized == "incorrect":
            snapshot = {
                "value_a": item.value_a,
                "value_b": item.value_b,
                "evidence_json": item.evidence_json,
            }
            if existing:
                existing.user_note = feedback_note
                existing.snapshot_json = _json.dumps(snapshot, ensure_ascii=False)
                existing.curation_status = "new"
                existing.created_at = datetime.now()
                existing.curated_at = None
            else:
                db.add(
                    FeedbackSample(
                        project_id=item.project_id,
                        audit_result_id=item.id,
                        audit_version=item.audit_version,
                        issue_type=item.type or "unknown",
                        severity=item.severity,
                        sheet_no_a=item.sheet_no_a,
                        sheet_no_b=item.sheet_no_b,
                        location=item.location,
                        description=item.description,
                        evidence_json=item.evidence_json,
                        value_a=item.value_a,
                        value_b=item.value_b,
                        user_note=feedback_note,
                        snapshot_json=_json.dumps(snapshot, ensure_ascii=False),
                    )
                )
        elif existing:
            db.delete(existing)


def _group_results_for_view(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return group_results_for_view(raw_items)


@router.get("/projects/{project_id}/audit/status", response_model=AuditStatusResponse)
def get_audit_status(project_id: str, db: Session = Depends(get_db)):
    """获取审核状态"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    from services.cache_service import recalculate_project_status

    previous = project.status
    next_status = recalculate_project_status(project_id, db)
    if next_status and next_status != previous:
        db.commit()
        db.refresh(project)

    from services.audit_runtime_service import (
        build_recent_event_snapshot,
        build_run_snapshot,
        get_audit_started_at_from_events,
        get_latest_run,
    )

    latest_run = get_latest_run(project_id, db)
    snapshot = (
        build_run_snapshot(latest_run)
        if latest_run
        else build_recent_event_snapshot(project_id, db)
    )
    response_status = project.status
    if snapshot["status"] == "planning" and response_status in {"new", "ready", "matching", "catalog_locked"}:
        response_status = "auditing"

    audit_version = snapshot["audit_version"]
    first_event_started_at = get_audit_started_at_from_events(project_id, audit_version, db)
    if first_event_started_at:
        snapshot_started_at = snapshot.get("started_at")
        if not snapshot_started_at or first_event_started_at < snapshot_started_at:
            snapshot["started_at"] = first_event_started_at
    if audit_version is None:
        latest_result = (
            db.query(AuditResult)
            .filter(AuditResult.project_id == project_id)
            .order_by(AuditResult.audit_version.desc())
            .first()
        )
        audit_version = latest_result.audit_version if latest_result else None

    total_issues = snapshot["total_issues"] or 0
    if audit_version is not None and total_issues == 0:
        total_issues = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_id == project_id,
                AuditResult.audit_version == audit_version,
            )
            .count()
        )

    return AuditStatusResponse(
        project_id=project_id,
        status=response_status,
        audit_version=audit_version,
        current_step=snapshot["current_step"],
        progress=int(snapshot["progress"] or (100 if response_status == "done" else 0)),
        total_issues=total_issues,
        run_status=snapshot["status"],
        provider_mode=snapshot.get("provider_mode"),
        error=snapshot["error"],
        started_at=snapshot["started_at"],
        finished_at=snapshot["finished_at"],
        scope_mode=snapshot.get("scope_mode"),
        scope_summary=snapshot.get("scope_summary"),
    )


@router.get(
    "/projects/{project_id}/audit/three-lines", response_model=ThreeLineMatchResponse
)
def get_three_line_match(project_id: str, db: Session = Depends(get_db)):
    """获取三线匹配状态（目录/PNG/JSON）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_service import match_three_lines

    result = match_three_lines(project_id, db)
    return result


@router.get(
    "/projects/{project_id}/audit/results", response_model=List[AuditResultResponse]
)
def get_audit_results(
    project_id: str,
    version: Optional[int] = Query(None, description="审核版本号"),
    type: Optional[str] = Query(None, description="问题类型筛选"),
    view: str = Query("raw", description="返回视图：raw/grouped"),
    db: Session = Depends(get_db),
):
    """获取审核结果"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if not version:
        latest = (
            db.query(AuditResult)
            .filter(AuditResult.project_id == project_id)
            .order_by(AuditResult.audit_version.desc())
            .first()
        )
        version = latest.audit_version if latest else 1

    query = db.query(AuditResult).filter(
        AuditResult.project_id == project_id, AuditResult.audit_version == version
    )

    if type:
        query = query.filter(AuditResult.type == type)

    raw_rows = query.order_by(AuditResult.created_at.asc()).all()
    raw_items = [_serialize_audit_result(item) for item in raw_rows]
    if view == "grouped":
        return _group_results_for_view(raw_items)
    return raw_items


@router.get(
    "/projects/{project_id}/audit/results/{result_id}/preview",
    response_model=AuditIssuePreviewResponse,
)
def get_audit_result_preview(
    project_id: str, result_id: str, db: Session = Depends(get_db)
):
    """获取单条审核结果对应的精确图纸预览信息。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    result = (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project_id,
            AuditResult.id == result_id,
        )
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="审核结果不存在")

    try:
        payload = get_issue_preview(result, db)
        db.commit()
        return payload
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))


def _stream_env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _serialize_audit_event_row(row: AuditRunEvent) -> AuditRunEventResponse:
    meta: Dict[str, Any] = {}
    if row.meta_json:
        try:
            parsed = _json.loads(row.meta_json)
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            meta = {}
    if row.event_kind == "runner_broadcast":
        meta.setdefault("stream_layer", "user_facing")
    return AuditRunEventResponse(
        id=row.id,
        audit_version=row.audit_version,
        level=row.level,
        step_key=row.step_key,
        agent_key=row.agent_key,
        agent_name=row.agent_name,
        event_kind=row.event_kind,
        progress_hint=row.progress_hint,
        message=row.message,
        created_at=row.created_at.isoformat() if row.created_at else None,
        meta=meta,
    )


def _resolve_audit_event_version(project_id: str, db: Session, version: Optional[int]) -> int:
    if version is not None:
        return version

    latest_run = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
        .first()
    )
    if latest_run:
        return latest_run.audit_version

    latest_event = (
        db.query(AuditRunEvent)
        .filter(AuditRunEvent.project_id == project_id)
        .order_by(AuditRunEvent.audit_version.desc(), AuditRunEvent.id.desc())
        .first()
    )
    return latest_event.audit_version if latest_event else 1


def _format_sse_event(*, event: str, data: Dict[str, Any], event_id: Optional[int] = None) -> str:
    lines: List[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {_json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


def _iter_audit_events_stream(project_id: str, version: int, since_id: Optional[int]):
    last_id = int(since_id or 0)
    heartbeat_seconds = _stream_env_float("AUDIT_STREAM_HEARTBEAT_SECONDS", 25.0)
    poll_seconds = _stream_env_float("AUDIT_STREAM_POLL_SECONDS", 1.0)
    test_once = str(os.getenv("AUDIT_STREAM_TEST_ONCE", "")).strip().lower() in {"1", "true", "yes", "on"}
    last_emit_at = time.monotonic()
    sent_any = False
    sent_heartbeat = False

    while True:
        db = SessionLocal()
        try:
            rows = (
                db.query(AuditRunEvent)
                .filter(
                    AuditRunEvent.project_id == project_id,
                    AuditRunEvent.audit_version == version,
                    AuditRunEvent.id > last_id,
                )
                .order_by(AuditRunEvent.id.asc())
                .limit(200)
                .all()
            )
        finally:
            db.close()

        if rows:
            for row in rows:
                payload = _serialize_audit_event_row(row).model_dump()
                event_name = str(row.event_kind or "phase_event").strip() or "phase_event"
                last_id = row.id
                last_emit_at = time.monotonic()
                sent_any = True
                yield _format_sse_event(event=event_name, data=payload, event_id=row.id)
            if test_once and since_id is not None:
                break
            continue

        if time.monotonic() - last_emit_at >= heartbeat_seconds:
            last_emit_at = time.monotonic()
            sent_any = True
            sent_heartbeat = True
            yield _format_sse_event(
                event="heartbeat",
                data={
                    "id": last_id,
                    "audit_version": version,
                    "event_kind": "heartbeat",
                    "message": "日志流连接正常，系统仍在等待新进展",
                },
                event_id=last_id if last_id > 0 else None,
            )
            if test_once:
                break

        if test_once and sent_any and sent_heartbeat:
            break
        time.sleep(poll_seconds)


def _iter_audit_results_stream(project_id: str, version: int, since_id: Optional[int]):
    last_id = int(since_id or 0)
    heartbeat_seconds = _stream_env_float("AUDIT_STREAM_HEARTBEAT_SECONDS", 25.0)
    poll_seconds = _stream_env_float("AUDIT_STREAM_POLL_SECONDS", 1.0)
    test_once = str(os.getenv("AUDIT_STREAM_TEST_ONCE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    tracked_kinds = {"result_upsert", "result_summary"}
    last_emit_at = time.monotonic()
    sent_any = False
    sent_heartbeat = False

    while True:
        db = SessionLocal()
        try:
            rows = (
                db.query(AuditRunEvent)
                .filter(
                    AuditRunEvent.project_id == project_id,
                    AuditRunEvent.audit_version == version,
                    AuditRunEvent.id > last_id,
                    AuditRunEvent.event_kind.in_(list(tracked_kinds)),
                )
                .order_by(AuditRunEvent.id.asc())
                .limit(200)
                .all()
            )
        finally:
            db.close()

        if rows:
            for row in rows:
                payload = _serialize_audit_event_row(row).model_dump()
                event_name = str(row.event_kind or "result_upsert").strip() or "result_upsert"
                last_id = row.id
                last_emit_at = time.monotonic()
                sent_any = True
                yield _format_sse_event(event=event_name, data=payload, event_id=row.id)
            if test_once and since_id is not None:
                break
            continue

        if time.monotonic() - last_emit_at >= heartbeat_seconds:
            last_emit_at = time.monotonic()
            sent_any = True
            sent_heartbeat = True
            yield _format_sse_event(
                event="heartbeat",
                data={
                    "id": last_id,
                    "audit_version": version,
                    "event_kind": "heartbeat",
                    "message": "结果流连接正常，系统仍在等待新问题",
                    "meta": {"stream_kind": "results"},
                },
                event_id=last_id if last_id > 0 else None,
            )
            if test_once:
                break

        if test_once and sent_any and sent_heartbeat:
            break
        time.sleep(poll_seconds)


class BatchPreviewRequest(BaseModel):
    result_ids: List[str]


class BatchAuditIssuePreviewResponse(BaseModel):
    issue: AuditIssuePreviewIssueResponse
    source: Optional[AuditIssueDrawingPreviewAssetResponse] = None
    target: Optional[AuditIssueDrawingPreviewAssetResponse] = None
    missing_reason: Optional[str] = None
    extra_source_anchors: List[Dict[str, Any]] = []
    extra_target_anchors: List[Dict[str, Any]] = []


@router.post(
    "/projects/{project_id}/audit/results/batch-preview",
    response_model=BatchAuditIssuePreviewResponse,
)
def batch_audit_result_preview(
    project_id: str,
    request: BatchPreviewRequest,
    db: Session = Depends(get_db),
):
    """获取分组审核结果的合并预览（叠加多个定位点）。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    result_ids = list(dict.fromkeys(request.result_ids or []))
    if not result_ids:
        raise HTTPException(status_code=400, detail="result_ids 不能为空")

    results = (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project_id,
            AuditResult.id.in_(result_ids),
        )
        .all()
    )
    if not results:
        raise HTTPException(status_code=404, detail="审核结果不存在")

    id_order = {rid: idx for idx, rid in enumerate(result_ids)}
    results.sort(key=lambda r: id_order.get(r.id, len(result_ids)))

    primary_result = results[0]
    try:
        primary_payload = get_issue_preview(primary_result, db)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))

    extra_source_anchors: List[Dict[str, Any]] = []
    extra_target_anchors: List[Dict[str, Any]] = []

    for result in results[1:]:
        try:
            extra_payload = get_issue_preview(result, db)
        except (ValueError, Exception):
            continue
        src = extra_payload.get("source")
        if src:
            anchor = (
                src.get("pdf_anchor") or src.get("layout_anchor") or src.get("anchor")
            )
            if anchor:
                extra_source_anchors.append(
                    {
                        **anchor,
                        "issue_id": result.id,
                        "location": result.location,
                    }
                )
        tgt = extra_payload.get("target")
        if tgt:
            anchor = (
                tgt.get("pdf_anchor") or tgt.get("layout_anchor") or tgt.get("anchor")
            )
            if anchor:
                extra_target_anchors.append(
                    {
                        **anchor,
                        "issue_id": result.id,
                        "location": result.location,
                    }
                )

    db.commit()

    return {
        **primary_payload,
        "extra_source_anchors": extra_source_anchors,
        "extra_target_anchors": extra_target_anchors,
    }


@router.patch("/projects/{project_id}/audit/results/batch")
def batch_update_audit_results(
    project_id: str,
    payload: BatchAuditResultUpdateRequest,
    db: Session = Depends(get_db),
):
    """批量更新审核结果处理状态"""
    _ensure_update_payload(payload.is_resolved, payload.feedback_status)
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    result_ids = list(dict.fromkeys(payload.result_ids or []))
    if not result_ids:
        raise HTTPException(status_code=400, detail="result_ids 不能为空")

    results = (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project_id,
            AuditResult.id.in_(result_ids),
        )
        .all()
    )
    if not results:
        raise HTTPException(status_code=404, detail="审核结果不存在")

    now = datetime.now()
    for item in results:
        _apply_audit_result_updates(
            item,
            is_resolved=payload.is_resolved,
            feedback_status=payload.feedback_status,
            feedback_note=payload.feedback_note,
            updated_at=now,
        )

    _sync_feedback_samples(db, results, payload.feedback_status, payload.feedback_note)
    db.commit()
    return {"success": True, "updated": len(results)}


@router.patch(
    "/projects/{project_id}/audit/results/{result_id}",
    response_model=AuditResultResponse,
)
def update_audit_result(
    project_id: str,
    result_id: str,
    payload: AuditResultUpdateRequest,
    db: Session = Depends(get_db),
):
    """更新单条审核结果的人工处理状态"""
    _ensure_update_payload(payload.is_resolved, payload.feedback_status)
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    result = (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project_id,
            AuditResult.id == result_id,
        )
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="审核结果不存在")

    _apply_audit_result_updates(
        result,
        is_resolved=payload.is_resolved,
        feedback_status=payload.feedback_status,
        feedback_note=payload.feedback_note,
        updated_at=datetime.now(),
    )
    _sync_feedback_samples(db, [result], payload.feedback_status, payload.feedback_note)
    db.commit()
    db.refresh(result)
    return _serialize_audit_result(result)


@router.get("/projects/{project_id}/audit/history")
def get_audit_history(project_id: str, db: Session = Depends(get_db)):
    """获取审核历史记录"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    runs = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
        .all()
    )

    if runs:
        history = []
        for run in runs:
            results = (
                db.query(AuditResult)
                .filter(
                    AuditResult.project_id == project_id,
                    AuditResult.audit_version == run.audit_version,
                )
                .all()
            )
            types = {}
            for item in results:
                types[item.type] = types.get(item.type, 0) + 1
            grouped_count = len(
                _group_results_for_view(
                    [_serialize_audit_result(item) for item in results]
                )
            )

            history.append(
                {
                    "version": run.audit_version,
                    "status": run.status,
                    "current_step": run.current_step,
                    "progress": run.progress,
                    "count": run.total_issues if run.total_issues else len(results),
                    "grouped_count": grouped_count,
                    "types": types,
                    "error": run.error,
                    "started_at": run.started_at.isoformat()
                    if run.started_at
                    else None,
                    "finished_at": run.finished_at.isoformat()
                    if run.finished_at
                    else None,
                    "scope_mode": getattr(run, "scope_mode", None),
                }
            )
        return history

    # 兼容旧数据：仅基于audit_results推导
    results = db.query(AuditResult).filter(AuditResult.project_id == project_id).all()
    history = {}
    for result in results:
        ver = result.audit_version
        if ver not in history:
            history[ver] = {
                "version": ver,
                "count": 0,
                "grouped_count": 0,
                "types": {},
                "status": "done",
            }
        history[ver]["count"] += 1
        t = result.type
        history[ver]["types"][t] = history[ver]["types"].get(t, 0) + 1
    for ver in list(history.keys()):
        version_items = [item for item in results if item.audit_version == ver]
        history[ver]["grouped_count"] = len(
            _group_results_for_view(
                [_serialize_audit_result(item) for item in version_items]
            )
        )
    return list(history.values())


@router.get(
    "/projects/{project_id}/audit/events", response_model=AuditRunEventListResponse
)
def get_audit_events(
    project_id: str,
    version: Optional[int] = Query(None, description="审核版本号"),
    since_id: Optional[int] = Query(None, description="增量拉取起点事件ID"),
    event_kinds: Optional[str] = Query(
        None, description="事件类型过滤，逗号分隔，例如 result_upsert,result_summary"
    ),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限"),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    version = _resolve_audit_event_version(project_id, db, version)

    query = db.query(AuditRunEvent).filter(
        AuditRunEvent.project_id == project_id,
        AuditRunEvent.audit_version == version,
    )
    if event_kinds:
        kinds = [item.strip() for item in event_kinds.split(",") if item.strip()]
        if kinds:
            query = query.filter(AuditRunEvent.event_kind.in_(kinds))
    if since_id is not None:
        query = query.filter(AuditRunEvent.id > since_id)

    rows = query.order_by(AuditRunEvent.id.asc()).limit(limit).all()
    items = [_serialize_audit_event_row(row) for row in rows]

    return {
        "items": items,
        "next_since_id": items[-1].id if items else since_id,
    }


@router.get("/projects/{project_id}/audit/events/stream")
def stream_audit_events(
    project_id: str,
    version: Optional[int] = Query(None, description="审核版本号"),
    since_id: Optional[int] = Query(None, description="增量拉取起点事件ID"),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    resolved_version = _resolve_audit_event_version(project_id, db, version)

    return StreamingResponse(
        _iter_audit_events_stream(project_id, resolved_version, since_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/projects/{project_id}/audit/results/stream")
def stream_audit_results(
    project_id: str,
    version: Optional[int] = Query(None, description="审核版本号"),
    since_id: Optional[int] = Query(None, description="增量拉取起点事件ID"),
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    resolved_version = _resolve_audit_event_version(project_id, db, version)

    return StreamingResponse(
        _iter_audit_results_stream(project_id, resolved_version, since_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/projects/{project_id}/audit/tasks", response_model=List[AuditTaskResponse]
)
def get_audit_tasks(
    project_id: str,
    version: Optional[int] = Query(None, description="审核版本号"),
    db: Session = Depends(get_db),
):
    """获取审核任务清单"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if version is None:
        latest_run = (
            db.query(AuditRun)
            .filter(AuditRun.project_id == project_id)
            .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
            .first()
        )
        if latest_run:
            version = latest_run.audit_version
        else:
            latest_task = (
                db.query(AuditTask)
                .filter(AuditTask.project_id == project_id)
                .order_by(AuditTask.audit_version.desc(), AuditTask.created_at.desc())
                .first()
            )
            version = latest_task.audit_version if latest_task else 1

    tasks = (
        db.query(AuditTask)
        .filter(
            AuditTask.project_id == project_id,
            AuditTask.audit_version == version,
        )
        .order_by(
            AuditTask.priority.asc(),
            AuditTask.task_type.asc(),
            AuditTask.created_at.asc(),
        )
        .all()
    )
    return tasks


@router.post("/projects/{project_id}/audit/tasks/plan")
def plan_audit_tasks(
    project_id: str,
    version: Optional[int] = Query(
        None, description="审核版本号，不传则按下一个版本规划"
    ),
    db: Session = Depends(get_db),
):
    """手动构建图纸上下文与审核任务图"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit.relationship_discovery import (
        discover_relationships,
        discover_relationships_v2,
        save_ai_edges,
    )
    from services.audit_runtime_service import get_next_audit_version
    from services.context_service import build_sheet_contexts
    from services.task_planner_service import build_audit_tasks

    audit_version = (
        version if version is not None else get_next_audit_version(project_id, db)
    )
    context_summary = build_sheet_contexts(project_id, db)
    use_v2 = str(os.getenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    ai_relationships = (
        discover_relationships_v2(project_id, db, audit_version=audit_version)
        if use_v2
        else discover_relationships(project_id, db, audit_version=audit_version)
    )
    relationship_count = save_ai_edges(project_id, ai_relationships, db)
    task_summary = build_audit_tasks(project_id, audit_version, db)
    return {
        "success": True,
        "audit_version": audit_version,
        "context_summary": context_summary,
        "relationship_summary": {
            "discovered": relationship_count,
        },
        "task_summary": task_summary,
    }


@router.post("/projects/{project_id}/audit/start")
def start_audit(
    project_id: str,
    request: Optional[StartAuditRequest] = None,
    db: Session = Depends(get_db),
):
    """开始审核"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_service import match_three_lines

    match_result = match_three_lines(project_id, db)
    summary = match_result["summary"]
    allow_incomplete = bool(request.allow_incomplete) if request else False
    if summary["total"] == 0:
        raise HTTPException(status_code=400, detail="请先锁定目录")
    if summary["ready"] != summary["total"] and not allow_incomplete:
        raise HTTPException(
            status_code=400,
            detail=(
                "三线匹配未完成："
                f"总数{summary['total']}，就绪{summary['ready']}，"
                f"缺PNG{summary['missing_png']}，缺JSON{summary['missing_json']}，"
                f"都缺{summary['missing_all']}"
            ),
        )

    from services.audit_runtime_service import (
        get_next_audit_version,
        start_audit_async,
        get_latest_run,
        is_project_running,
        mark_stale_running_runs,
    )
    from services.audit_runtime.providers.factory import normalize_provider_mode

    if is_project_running(project_id):
        latest_run = get_latest_run(project_id, db)
        return {
            "success": True,
            "message": "审核任务已在运行",
            "audit_version": latest_run.audit_version if latest_run else None,
        }

    mark_stale_running_runs(project_id, db)

    from services.audit_runtime_service import _set_running, _clear_running

    if not _set_running(project_id):
        raise HTTPException(status_code=409, detail="该项目已有审核任务在运行")

    new_version = get_next_audit_version(project_id, db)
    provider_mode = normalize_provider_mode(request.provider_mode if request else None)

    run = AuditRun(
        project_id=project_id,
        audit_version=new_version,
        status="running",
        current_step="等待执行",
        progress=0,
        total_issues=0,
        provider_mode=provider_mode,
        scope_mode="partial"
        if (allow_incomplete and summary["ready"] < summary["total"])
        else "full",
        scope_summary=_json.dumps(summary, ensure_ascii=False),
    )
    db.add(run)
    project.status = "auditing"
    db.commit()

    try:
        start_audit_async(
            project_id,
            new_version,
            allow_incomplete=allow_incomplete,
            provider_mode=provider_mode,
        )
    except RuntimeError as exc:
        run.status = "failed"
        run.current_step = "启动失败"
        run.error = str(exc)
        run.finished_at = datetime.now()
        project.status = "ready"
        db.commit()
        _clear_running(project_id)
        raise HTTPException(status_code=409, detail=str(exc))

    return {"success": True, "message": "审核已开始", "audit_version": new_version}


@router.post("/projects/{project_id}/audit/stop")
def stop_audit(project_id: str, db: Session = Depends(get_db)):
    """强制中断当前审核任务，并清空本次审核的状态、记录和缓存。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    running_run = (
        db.query(AuditRun)
        .filter(
            AuditRun.project_id == project_id,
            AuditRun.status == "running",
        )
        .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
        .first()
    )
    if not running_run:
        return {"success": True, "message": "当前没有运行中的审核任务"}

    from services.audit_runtime.cancel_registry import request_cancel
    from services.audit_runtime.agent_runner import ProjectAuditAgentRunner

    audit_version = running_run.audit_version
    request_cancel(project_id)
    running_run.status = "stopping"
    running_run.current_step = "正在中断（用户请求）"
    running_run.error = "用户手动停止"
    running_run.updated_at = datetime.now()
    db.commit()

    runner = ProjectAuditAgentRunner.get_existing(
        project_id,
        audit_version=audit_version,
    )
    if runner is not None:
        try:
            runner.cancel_active_turns()
        except Exception:
            logger.exception("停止审核时取消活跃 Runner 调用失败: project=%s version=%s", project_id, audit_version)

    sync_result = _finalize_stopped_audit_version_cleanup(
        project_id,
        audit_version,
        wait_timeout_seconds=0.5,
    )
    if sync_result is not None:
        return sync_result

    _schedule_stopped_audit_version_cleanup(project_id, audit_version)
    return {
        "success": True,
        "message": "停止请求已受理，后台会在安全点完成清理",
        "audit_version": audit_version,
        "stopped": False,
        "cleanup_scheduled": True,
        "deleted": {
            "results": 0,
            "runs": 0,
            "tasks": 0,
            "events": 0,
            "feedback_samples": 0,
            "issue_drawings": 0,
            "annotations": 0,
        },
        "artifacts": {
            "cache_files": 0,
            "report_files": 0,
        },
    }


def _finalize_stopped_audit_version_cleanup(
    project_id: str,
    audit_version: int,
    *,
    wait_timeout_seconds: float,
) -> Optional[Dict[str, object]]:
    from services.audit_runtime.cancel_registry import clear_cancel_request
    from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
    from services.audit_runtime_service import _clear_running, wait_for_project_stop
    from services.cache_service import (
        recalculate_project_status,
        increment_cache_version,
    )

    stopped = wait_for_project_stop(project_id, timeout_seconds=wait_timeout_seconds)
    if not stopped:
        return None

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            _clear_running(project_id)
            clear_cancel_request(project_id)
            ProjectAuditAgentRunner.drop(project_id, audit_version=audit_version)
            return {
                "success": True,
                "message": "审核已停止，但项目已不存在",
                "audit_version": audit_version,
                "stopped": True,
                "deleted": {
                    "results": 0,
                    "runs": 0,
                    "tasks": 0,
                    "events": 0,
                    "feedback_samples": 0,
                    "issue_drawings": 0,
                    "annotations": 0,
                },
                "artifacts": {
                    "cache_files": 0,
                    "report_files": 0,
                },
            }

        deleted = _delete_audit_version_records(project_id, audit_version, db)
        cache_files_deleted = _clear_audit_version_cache(project, audit_version, db)
        report_files_deleted = _clear_audit_version_report_files(project, audit_version)
        recalculate_project_status(project_id, db)
        db.commit()
        increment_cache_version(project_id, db)
    finally:
        db.close()

    _clear_running(project_id)
    clear_cancel_request(project_id)
    ProjectAuditAgentRunner.drop(project_id, audit_version=audit_version)
    return {
        "success": True,
        "message": "当前审核已终止并清理完成",
        "audit_version": audit_version,
        "stopped": True,
        "deleted": deleted,
        "artifacts": {
            "cache_files": cache_files_deleted,
            "report_files": report_files_deleted,
        },
    }


def _run_stopped_audit_version_cleanup(project_id: str, audit_version: int) -> None:
    try:
        result = _finalize_stopped_audit_version_cleanup(
            project_id,
            audit_version,
            wait_timeout_seconds=20.0,
        )
        if result is None:
            from services.audit_runtime.cancel_registry import clear_cancel_request
            from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
            from services.audit_runtime_service import _clear_running

            logger.warning(
                "停止审核后台收尾超时，强制清理运行态: project=%s version=%s",
                project_id,
                audit_version,
            )
            _clear_running(project_id)
            clear_cancel_request(project_id)
            ProjectAuditAgentRunner.drop(project_id, audit_version=audit_version)
    except Exception:
        logger.exception(
            "停止审核后台收尾失败: project=%s version=%s",
            project_id,
            audit_version,
        )
    finally:
        with _STOP_CLEANUP_LOCK:
            _STOP_CLEANUP_JOBS.discard((project_id, int(audit_version)))


def _schedule_stopped_audit_version_cleanup(project_id: str, audit_version: int) -> bool:
    key = (project_id, int(audit_version))
    with _STOP_CLEANUP_LOCK:
        if key in _STOP_CLEANUP_JOBS:
            return False
        _STOP_CLEANUP_JOBS.add(key)

    worker = threading.Thread(
        target=_run_stopped_audit_version_cleanup,
        args=(project_id, int(audit_version)),
        daemon=True,
    )
    worker.start()
    return True


def _clear_audit_version_cache(project, version: int, db) -> int:
    """清理指定审核版本的文件缓存

    策略：
    - 如果删除后没有其他审核版本，清空整个 dimension-v1 缓存目录
    - 如果还有其他版本，保留缓存供复用（缓存键包含版本号哈希，不会冲突）

    Args:
        project: 项目对象
        version: 审核版本号
        db: 数据库会话

    Returns:
        删除的文件数量
    """
    from pathlib import Path
    from services.storage_path_service import resolve_project_dir
    from models import AuditRun, AuditResult

    # 检查是否还有其他版本的审核记录
    other_versions = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project.id, AuditRun.audit_version != version)
        .first()
    ) or (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project.id, AuditResult.audit_version != version
        )
        .first()
    )

    # 如果还有其他版本，保留缓存供复用
    if other_versions:
        return 0

    # 没有其他版本，清空整个缓存目录
    cache_dir = resolve_project_dir(project, ensure=False) / "cache" / "dimension-v1"
    if not cache_dir.exists():
        return 0

    deleted_count = 0
    for cache_file in cache_dir.glob("*.json"):
        try:
            cache_file.unlink()
            deleted_count += 1
        except Exception:
            # 忽略删除失败的文件
            pass

    return deleted_count


def _clear_audit_version_report_files(project, version: int) -> int:
    """删除指定审核版本的报告产物。"""
    from services.storage_path_service import resolve_project_dir

    reports_dir = resolve_project_dir(project, ensure=False) / "reports"
    if not reports_dir.exists():
        return 0

    deleted_count = 0
    for path in (
        reports_dir / f"report_v{version}.pdf",
        reports_dir / f"report_v{version}.xlsx",
        reports_dir / f"report_v{version}_marked.pdf",
        reports_dir / f"report_v{version}_anchors.json",
    ):
        if not path.exists():
            continue
        try:
            path.unlink()
            deleted_count += 1
        except Exception:
            pass

    annotated_dir = reports_dir / f"annotated_v{version}"
    if annotated_dir.exists():
        import shutil

        try:
            deleted_count += sum(1 for child in annotated_dir.rglob("*") if child.is_file())
            shutil.rmtree(annotated_dir)
        except Exception:
            pass

    return deleted_count


def _delete_audit_version_records(
    project_id: str,
    version: Optional[int],
    db: Session,
) -> Dict[str, int]:
    version_filters = [AuditResult.project_id == project_id]
    run_filters = [AuditRun.project_id == project_id]
    task_filters = [AuditTask.project_id == project_id]
    event_filters = [AuditRunEvent.project_id == project_id]
    feedback_filters = [FeedbackSample.project_id == project_id]
    issue_drawing_filters = [AuditIssueDrawing.project_id == project_id]
    annotation_filters = [DrawingAnnotation.project_id == project_id]
    if version is not None:
        version_filters.append(AuditResult.audit_version == version)
        run_filters.append(AuditRun.audit_version == version)
        task_filters.append(AuditTask.audit_version == version)
        event_filters.append(AuditRunEvent.audit_version == version)
        feedback_filters.append(FeedbackSample.audit_version == version)
        issue_drawing_filters.append(AuditIssueDrawing.audit_version == version)
        annotation_filters.append(DrawingAnnotation.audit_version == version)

    deleted_results = db.query(AuditResult).filter(*version_filters).delete(synchronize_session=False)
    deleted_runs = db.query(AuditRun).filter(*run_filters).delete(synchronize_session=False)
    deleted_tasks = db.query(AuditTask).filter(*task_filters).delete(synchronize_session=False)
    deleted_events = db.query(AuditRunEvent).filter(*event_filters).delete(synchronize_session=False)
    deleted_feedback_samples = db.query(FeedbackSample).filter(*feedback_filters).delete(synchronize_session=False)
    deleted_issue_drawings = db.query(AuditIssueDrawing).filter(*issue_drawing_filters).delete(synchronize_session=False)
    deleted_annotations = db.query(DrawingAnnotation).filter(*annotation_filters).delete(synchronize_session=False)
    return {
        "results": deleted_results,
        "runs": deleted_runs,
        "tasks": deleted_tasks,
        "events": deleted_events,
        "feedback_samples": deleted_feedback_samples,
        "issue_drawings": deleted_issue_drawings,
        "annotations": deleted_annotations,
    }


@router.post("/projects/{project_id}/audit/run")
def run_audit(project_id: str, db: Session = Depends(get_db)):
    """执行审核（三步）/查询当前执行快照（兼容旧前端）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_runtime_service import get_latest_run

    run = get_latest_run(project_id, db)
    if not run:
        # 兼容旧逻辑：若前端直接调用run，自动触发start
        return start_audit(project_id, None, db)

    response = {
        "success": True,
        "audit_version": run.audit_version,
        "status": run.status,
        "progress": run.progress,
        "current_step": run.current_step,
        "total_issues": run.total_issues,
        "error": run.error,
    }

    if run.status == "done":
        typed_counts = {}
        items = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_id == project_id,
                AuditResult.audit_version == run.audit_version,
            )
            .all()
        )
        for issue in items:
            typed_counts[issue.type] = typed_counts.get(issue.type, 0) + 1
        response.update(
            {
                "index_issues": typed_counts.get("index", 0),
                "dimension_issues": typed_counts.get("dimension", 0),
                "material_issues": typed_counts.get("material", 0),
            }
        )

    return response


@router.post("/projects/{project_id}/audit/clear")
def clear_audit_report(project_id: str, db: Session = Depends(get_db)):
    """清空项目审核报告（结果、运行记录与任务记录）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    deleted = _delete_audit_version_records(project_id, None, db)

    from services.cache_service import (
        recalculate_project_status,
        increment_cache_version,
    )

    recalculate_project_status(project_id, db)
    db.commit()
    increment_cache_version(project_id, db)

    return {
        "success": True,
        "deleted": deleted,
    }


@router.delete("/projects/{project_id}/audit/version/{version}")
def delete_audit_version(project_id: str, version: int, db: Session = Depends(get_db)):
    """删除单个审核版本（结果、运行记录与任务记录）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    running = (
        db.query(AuditRun)
        .filter(
            AuditRun.project_id == project_id,
            AuditRun.audit_version == version,
            AuditRun.status == "running",
        )
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail="该审核版本仍在运行，无法删除")

    deleted = _delete_audit_version_records(project_id, version, db)

    if sum(deleted.values()) == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail=f"审核版本 v{version} 不存在")

    # 清理该审核版本的文件缓存
    _clear_audit_version_cache(project, version, db)

    from services.cache_service import (
        recalculate_project_status,
        increment_cache_version,
    )

    recalculate_project_status(project_id, db)
    db.commit()
    increment_cache_version(project_id, db)

    latest_run = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
        .first()
    )
    if latest_run:
        latest_remaining_version = latest_run.audit_version
    else:
        latest_result = (
            db.query(AuditResult)
            .filter(AuditResult.project_id == project_id)
            .order_by(AuditResult.audit_version.desc())
            .first()
        )
        latest_remaining_version = (
            latest_result.audit_version if latest_result else None
        )

    return {
        "success": True,
        "deleted": deleted,
        "latest_remaining_version": latest_remaining_version,
    }
