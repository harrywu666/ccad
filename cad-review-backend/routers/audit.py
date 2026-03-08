"""
审核管理路由
提供审核启动、进度查询、结果查询接口
"""

from typing import Any, Dict, List, Literal, Optional, Tuple
from datetime import datetime
import hashlib
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, ConfigDict
from database import get_db
import json as _json
from models import Project, AuditResult, AuditRun, AuditTask, FeedbackSample
from services.audit.issue_preview import get_issue_preview

router = APIRouter()

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
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


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


class ThreeLineMatchResponse(BaseModel):
    project_id: str
    summary: ThreeLineSummaryResponse
    items: List[ThreeLineItemResponse]


class StartAuditRequest(BaseModel):
    allow_incomplete: bool = False


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


def _normalize_index_description(description: Optional[str]) -> str:
    text = (description or "").strip()
    if not text:
        return ""
    # 将“索引A1/索引6”这类位置标签归一，便于相似问题合并
    text = re.sub(r"中的索引[^\s，。]+", "中的索引*", text)
    text = re.sub(r"索引[\w\-.]+", "索引*", text)
    return text


def _serialize_audit_result(item: AuditResult) -> Dict[str, Any]:
    location = item.location.strip() if isinstance(item.location, str) else item.location
    feedback_status = _normalize_feedback_status(item.feedback_status)
    return {
        "id": item.id,
        "project_id": item.project_id,
        "audit_version": item.audit_version,
        "type": item.type,
        "severity": item.severity,
        "sheet_no_a": item.sheet_no_a,
        "sheet_no_b": item.sheet_no_b,
        "location": location,
        "locations": [location] if location else [],
        "occurrence_count": 1,
        "value_a": item.value_a,
        "value_b": item.value_b,
        "description": item.description,
        "evidence_json": item.evidence_json,
        "is_resolved": bool(item.is_resolved),
        "resolved_at": item.resolved_at,
        "feedback_status": feedback_status,
        "feedback_at": item.feedback_at if feedback_status == "incorrect" else None,
        "feedback_note": item.feedback_note if feedback_status == "incorrect" else None,
        "is_grouped": False,
        "group_id": None,
        "issue_ids": [item.id],
    }


def _normalize_feedback_status(value: Optional[str]) -> AuditFeedbackStatus:
    return "incorrect" if value == "incorrect" else "none"


def _ensure_update_payload(
    is_resolved: Optional[bool],
    feedback_status: Optional[AuditFeedbackStatus],
) -> None:
    if is_resolved is None and feedback_status is None:
        raise HTTPException(status_code=400, detail="至少提供 is_resolved 或 feedback_status")


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
                db.add(FeedbackSample(
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
                ))
        elif existing:
            db.delete(existing)


def _group_results_for_view(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for item in raw_items:
        if item.get("type") == "index":
            key = (
                "index",
                item.get("sheet_no_a") or "",
                item.get("sheet_no_b") or "",
                _normalize_index_description(item.get("description")),
            )
        else:
            # 仅对索引问题做合并，其他类型保留单条
            key = ("single", item["id"])
        groups.setdefault(key, []).append(item)

    grouped: List[Dict[str, Any]] = []
    for key, entries in groups.items():
        if len(entries) == 1 and key[0] == "single":
            grouped.append(entries[0])
            continue

        first = entries[0]
        issue_ids = [entry["id"] for entry in entries]
        all_locations: List[str] = []
        for entry in entries:
            for loc in entry.get("locations") or []:
                if isinstance(loc, str) and loc and loc not in all_locations:
                    all_locations.append(loc)

        if not all_locations and first.get("location"):
            all_locations = [first["location"]]

        if len(all_locations) <= 4:
            location_text = "、".join(all_locations) if all_locations else first.get("location")
        else:
            location_text = f"{'、'.join(all_locations[:4])} 等{len(all_locations)}处"

        resolved_values = [bool(entry.get("is_resolved")) for entry in entries]
        is_resolved = all(resolved_values) if resolved_values else False
        resolved_candidates = [entry.get("resolved_at") for entry in entries if entry.get("resolved_at")]
        resolved_at = max(resolved_candidates) if (is_resolved and resolved_candidates) else None
        feedback_values = [_normalize_feedback_status(entry.get("feedback_status")) for entry in entries]
        feedback_status = "incorrect" if any(value == "incorrect" for value in feedback_values) else "none"
        feedback_candidates = [entry.get("feedback_at") for entry in entries if entry.get("feedback_at")]
        feedback_at = max(feedback_candidates) if (feedback_status == "incorrect" and feedback_candidates) else None
        feedback_notes = [entry.get("feedback_note") for entry in entries if entry.get("feedback_note")]
        feedback_note = feedback_notes[0] if (feedback_status == "incorrect" and feedback_notes) else None

        key_text = "|".join(str(part) for part in key)
        group_id = f"group_{hashlib.md5(key_text.encode('utf-8')).hexdigest()[:16]}"

        grouped.append(
            {
                **first,
                "id": group_id,
                "location": location_text,
                "locations": all_locations,
                "occurrence_count": len(issue_ids),
                "is_resolved": is_resolved,
                "resolved_at": resolved_at,
                "feedback_status": feedback_status,
                "feedback_at": feedback_at,
                "feedback_note": feedback_note,
                "is_grouped": True,
                "group_id": group_id,
                "issue_ids": issue_ids,
            }
        )

    return grouped


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

    from services.audit_runtime_service import get_latest_run, build_run_snapshot

    latest_run = get_latest_run(project_id, db)
    snapshot = build_run_snapshot(latest_run)

    audit_version = snapshot["audit_version"]
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
        status=project.status,
        audit_version=audit_version,
        current_step=snapshot["current_step"],
        progress=int(snapshot["progress"] or (100 if project.status == "done" else 0)),
        total_issues=total_issues,
        run_status=snapshot["status"],
        error=snapshot["error"],
        started_at=snapshot["started_at"],
        finished_at=snapshot["finished_at"],
    )


@router.get("/projects/{project_id}/audit/three-lines", response_model=ThreeLineMatchResponse)
def get_three_line_match(project_id: str, db: Session = Depends(get_db)):
    """获取三线匹配状态（目录/PNG/JSON）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_service import match_three_lines

    result = match_three_lines(project_id, db)
    return result


@router.get("/projects/{project_id}/audit/results", response_model=List[AuditResultResponse])
def get_audit_results(
    project_id: str, 
    version: Optional[int] = Query(None, description="审核版本号"),
    type: Optional[str] = Query(None, description="问题类型筛选"),
    view: str = Query("raw", description="返回视图：raw/grouped"),
    db: Session = Depends(get_db)
):
    """获取审核结果"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    if not version:
        latest = db.query(AuditResult).filter(
            AuditResult.project_id == project_id
        ).order_by(AuditResult.audit_version.desc()).first()
        version = latest.audit_version if latest else 1
    
    query = db.query(AuditResult).filter(
        AuditResult.project_id == project_id,
        AuditResult.audit_version == version
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
def get_audit_result_preview(project_id: str, result_id: str, db: Session = Depends(get_db)):
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


@router.patch("/projects/{project_id}/audit/results/{result_id}", response_model=AuditResultResponse)
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
            grouped_count = len(_group_results_for_view([_serialize_audit_result(item) for item in results]))

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
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                }
            )
        return history

    # 兼容旧数据：仅基于audit_results推导
    results = db.query(AuditResult).filter(AuditResult.project_id == project_id).all()
    history = {}
    for result in results:
        ver = result.audit_version
        if ver not in history:
            history[ver] = {"version": ver, "count": 0, "grouped_count": 0, "types": {}, "status": "done"}
        history[ver]["count"] += 1
        t = result.type
        history[ver]["types"][t] = history[ver]["types"].get(t, 0) + 1
    for ver in list(history.keys()):
        version_items = [item for item in results if item.audit_version == ver]
        history[ver]["grouped_count"] = len(_group_results_for_view([_serialize_audit_result(item) for item in version_items]))
    return list(history.values())


@router.get("/projects/{project_id}/audit/tasks", response_model=List[AuditTaskResponse])
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
        .order_by(AuditTask.priority.asc(), AuditTask.task_type.asc(), AuditTask.created_at.asc())
        .all()
    )
    return tasks


@router.post("/projects/{project_id}/audit/tasks/plan")
def plan_audit_tasks(
    project_id: str,
    version: Optional[int] = Query(None, description="审核版本号，不传则按下一个版本规划"),
    db: Session = Depends(get_db),
):
    """手动构建图纸上下文与审核任务图"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_runtime_service import get_next_audit_version
    from services.context_service import build_sheet_contexts
    from services.task_planner_service import build_audit_tasks

    audit_version = version if version is not None else get_next_audit_version(project_id, db)
    context_summary = build_sheet_contexts(project_id, db)
    task_summary = build_audit_tasks(project_id, audit_version, db)
    return {
        "success": True,
        "audit_version": audit_version,
        "context_summary": context_summary,
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

    run = AuditRun(
        project_id=project_id,
        audit_version=new_version,
        status="running",
        current_step="等待执行",
        progress=0,
        total_issues=0,
    )
    db.add(run)
    project.status = "auditing"
    db.commit()

    try:
        start_audit_async(project_id, new_version, allow_incomplete=allow_incomplete)
    except RuntimeError as exc:
        run.status = "failed"
        run.current_step = "启动失败"
        run.error = str(exc)
        run.finished_at = datetime.now()
        project.status = "ready"
        db.commit()
        _clear_running(project_id)
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "success": True,
        "message": "审核已开始",
        "audit_version": new_version
    }


@router.post("/projects/{project_id}/audit/stop")
def stop_audit(project_id: str, db: Session = Depends(get_db)):
    """中断当前审核任务（协作取消）。"""
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

    request_cancel(project_id)
    running_run.current_step = "正在中断（用户请求）"
    db.commit()
    return {
        "success": True,
        "message": "已发送中断请求",
        "audit_version": running_run.audit_version,
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

    deleted_results = (
        db.query(AuditResult)
        .filter(AuditResult.project_id == project_id)
        .delete(synchronize_session=False)
    )
    deleted_runs = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .delete(synchronize_session=False)
    )
    deleted_tasks = (
        db.query(AuditTask)
        .filter(AuditTask.project_id == project_id)
        .delete(synchronize_session=False)
    )

    from services.cache_service import recalculate_project_status, increment_cache_version

    recalculate_project_status(project_id, db)
    db.commit()
    increment_cache_version(project_id, db)

    return {
        "success": True,
        "deleted": {
            "results": deleted_results,
            "runs": deleted_runs,
            "tasks": deleted_tasks,
        },
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

    deleted_results = (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project_id,
            AuditResult.audit_version == version,
        )
        .delete(synchronize_session=False)
    )
    deleted_runs = (
        db.query(AuditRun)
        .filter(
            AuditRun.project_id == project_id,
            AuditRun.audit_version == version,
        )
        .delete(synchronize_session=False)
    )
    deleted_tasks = (
        db.query(AuditTask)
        .filter(
            AuditTask.project_id == project_id,
            AuditTask.audit_version == version,
        )
        .delete(synchronize_session=False)
    )

    if (deleted_results + deleted_runs + deleted_tasks) == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail=f"审核版本 v{version} 不存在")

    from services.cache_service import recalculate_project_status, increment_cache_version

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
        latest_remaining_version = latest_result.audit_version if latest_result else None

    return {
        "success": True,
        "deleted": {
            "results": deleted_results,
            "runs": deleted_runs,
            "tasks": deleted_tasks,
        },
        "latest_remaining_version": latest_remaining_version,
    }
