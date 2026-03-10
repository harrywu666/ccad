"""审核运行态更新与任务状态迁移。"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from domain.sheet_normalization import normalize_sheet_no
from database import SessionLocal
from models import AuditRun, AuditRunEvent, AuditTask, Project


_STEP_AGENT_DEFAULTS: Dict[str, Dict[str, object]] = {
    "prepare": {
        "agent_key": "master_planner_agent",
        "agent_name": "总控规划Agent",
        "event_kind": "phase_started",
        "progress_hint": 5,
    },
    "context": {
        "agent_key": "master_planner_agent",
        "agent_name": "总控规划Agent",
        "event_kind": "phase_progress",
        "progress_hint": 10,
    },
    "relationship_discovery": {
        "agent_key": "relationship_review_agent",
        "agent_name": "关系审查Agent",
        "event_kind": "phase_progress",
        "progress_hint": 12,
    },
    "task_planning": {
        "agent_key": "master_planner_agent",
        "agent_name": "总控规划Agent",
        "event_kind": "phase_progress",
        "progress_hint": 18,
    },
    "index": {
        "agent_key": "index_review_agent",
        "agent_name": "索引审查Agent",
        "event_kind": "phase_progress",
        "progress_hint": 35,
    },
    "dimension": {
        "agent_key": "dimension_review_agent",
        "agent_name": "尺寸审查Agent",
        "event_kind": "phase_progress",
        "progress_hint": 60,
    },
    "material": {
        "agent_key": "material_review_agent",
        "agent_name": "材料审查Agent",
        "event_kind": "phase_progress",
        "progress_hint": 78,
    },
    "report": {
        "agent_key": "master_planner_agent",
        "agent_name": "总控规划Agent",
        "event_kind": "phase_completed",
        "progress_hint": 95,
    },
}

_OBSERVER_TRIGGER_EVENT_KINDS = {
    "runner_turn_started",
    "provider_stream_delta",
    "output_validation_failed",
    "runner_turn_retrying",
    "runner_turn_needs_review",
}


class _PassiveObserverProvider:
    async def observe_once(self, snapshot, memory):  # noqa: ANN001
        return None


def _resolve_event_defaults(step_key: Optional[str]) -> Dict[str, object]:
    key = (step_key or "").strip()
    if key and key in _STEP_AGENT_DEFAULTS:
        return dict(_STEP_AGENT_DEFAULTS[key])
    return {
        "agent_key": "master_planner_agent",
        "agent_name": "总控规划Agent",
        "event_kind": "phase_progress",
        "progress_hint": 0,
    }


def update_run_progress(
    project_id: str,
    audit_version: int,
    *,
    status: Optional[str] = None,
    current_step: Optional[str] = None,
    progress: Optional[int] = None,
    total_issues: Optional[int] = None,
    error: Optional[str] = None,
    finished: bool = False,
) -> None:
    db = SessionLocal()
    try:
        run = (
            db.query(AuditRun)
            .filter(
                AuditRun.project_id == project_id,
                AuditRun.audit_version == audit_version,
            )
            .first()
        )
        if not run:
            return

        if status is not None:
            run.status = status
        if current_step is not None:
            run.current_step = current_step
        if progress is not None:
            run.progress = max(0, min(100, int(progress)))
        if total_issues is not None:
            run.total_issues = int(total_issues)
        if error is not None:
            run.error = error
        if finished:
            run.finished_at = datetime.now()

        run.updated_at = datetime.now()
        db.commit()
    finally:
        db.close()


def set_project_status(project_id: str, status: str) -> None:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return
        project.status = status
        db.commit()
    finally:
        db.close()


def append_run_event(
    project_id: str,
    audit_version: int,
    *,
    level: str = "info",
    step_key: Optional[str] = None,
    agent_key: Optional[str] = None,
    agent_name: Optional[str] = None,
    event_kind: Optional[str] = None,
    progress_hint: Optional[int] = None,
    message: str,
    meta: Optional[Dict[str, object]] = None,
    dispatch_observer: bool = True,
) -> None:
    db = SessionLocal()
    try:
        defaults = _resolve_event_defaults(step_key)
        event = AuditRunEvent(
            project_id=project_id,
            audit_version=audit_version,
            level=(level or "info").strip() or "info",
            step_key=(step_key or "").strip() or None,
            agent_key=(agent_key or str(defaults["agent_key"])).strip() or None,
            agent_name=(agent_name or str(defaults["agent_name"])).strip() or None,
            event_kind=(event_kind or str(defaults["event_kind"])).strip() or None,
            progress_hint=(
                int(progress_hint)
                if progress_hint is not None
                else int(defaults["progress_hint"])
            ),
            message=message.strip(),
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        )
        db.add(event)
        db.commit()
    finally:
        db.close()
    if dispatch_observer:
        _dispatch_runner_observer(
            project_id,
            audit_version,
            event_kind=(event_kind or str(_resolve_event_defaults(step_key)["event_kind"])).strip() or None,
        )


def _run_async(coro):  # noqa: ANN001
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if not loop.is_running():
        return loop.run_until_complete(coro)

    holder: Dict[str, Any] = {}

    def _runner() -> None:
        try:
            holder["result"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in holder:
        raise holder["error"]
    return holder.get("result")


def _load_observer_runtime_status(project_id: str, audit_version: int) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        run = (
            db.query(AuditRun)
            .filter(
                AuditRun.project_id == project_id,
                AuditRun.audit_version == audit_version,
            )
            .first()
        )
        if not run:
            rows = (
                db.query(AuditRunEvent)
                .filter(
                    AuditRunEvent.project_id == project_id,
                    AuditRunEvent.audit_version == audit_version,
                )
                .order_by(AuditRunEvent.id.desc())
                .limit(20)
                .all()
            )
            provider_mode = None
            current_step = None
            progress = None
            for row in rows:
                if current_step is None and getattr(row, "step_key", None):
                    current_step = row.step_key
                if progress is None and getattr(row, "progress_hint", None) is not None:
                    progress = row.progress_hint
                try:
                    meta = json.loads(row.meta_json) if row.meta_json else {}
                except Exception:
                    meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                if provider_mode is None:
                    provider_mode = (
                        str(meta.get("provider_mode") or "").strip()
                        or str(meta.get("provider_name") or "").strip()
                        or None
                    )
                if current_step and progress is not None and provider_mode:
                    break
            return {
                "status": "running",
                "current_step": current_step,
                "progress": progress,
                "provider_mode": provider_mode,
            }
        return {
            "status": getattr(run, "status", None),
            "current_step": getattr(run, "current_step", None),
            "progress": getattr(run, "progress", None),
            "provider_mode": getattr(run, "provider_mode", None),
        }
    finally:
        db.close()


def _load_recent_observer_events(project_id: str, audit_version: int, *, limit: int = 8) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(AuditRunEvent)
            .filter(
                AuditRunEvent.project_id == project_id,
                AuditRunEvent.audit_version == audit_version,
            )
            .order_by(AuditRunEvent.id.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()

    items: List[Dict[str, Any]] = []
    for row in reversed(rows):
        try:
            meta = json.loads(row.meta_json) if row.meta_json else {}
        except Exception:
            meta = {}
        items.append(
            {
                "event_kind": row.event_kind,
                "message": row.message,
                "agent_key": row.agent_key,
                "agent_name": row.agent_name,
                "step_key": row.step_key,
                "meta": meta if isinstance(meta, dict) else {},
            }
        )
    return items


def _dispatch_runner_observer(
    project_id: str,
    audit_version: int,
    *,
    event_kind: Optional[str],
) -> None:
    normalized_kind = str(event_kind or "").strip()
    if normalized_kind not in _OBSERVER_TRIGGER_EVENT_KINDS:
        return

    from services.audit_runtime.runner_observer_feed import build_observer_snapshot
    from services.audit_runtime.runner_observer_session import ProjectRunnerObserverSession
    from services.audit_runtime.providers.factory import build_runner_provider

    runtime_status = _load_observer_runtime_status(project_id, audit_version)
    recent_events = _load_recent_observer_events(project_id, audit_version)
    provider_mode = str(runtime_status.get("provider_mode") or "").strip() or None
    observer = ProjectRunnerObserverSession.get_or_create(
        project_id,
        audit_version=audit_version,
        provider=build_runner_provider(requested_mode=provider_mode) if provider_mode else _PassiveObserverProvider(),
    )
    try:
        decision = _run_async(
            observer.observe(
                build_observer_snapshot(
                    project_id=project_id,
                    audit_version=audit_version,
                    runtime_status=runtime_status,
                    recent_events=recent_events,
                )
            )
        )
    except NotImplementedError:
        return
    except Exception:
        return
    if not decision:
        return
    observer_provider = getattr(observer, "provider", None)
    observer_provider_name = getattr(observer_provider, "provider_name", "unknown")

    append_run_event(
        project_id,
        audit_version,
        step_key=runtime_status.get("current_step") or None,
        agent_key="runner_observer_agent",
        agent_name="Runner观察Agent",
        event_kind="runner_observer_decision",
        progress_hint=runtime_status.get("progress") or 0,
        message=str(getattr(decision, "summary", "") or "Runner 已更新现场判断"),
        meta={
            "stream_layer": "observer_reasoning",
            "provider_name": observer_provider_name,
            "provider_mode": provider_mode or observer_provider_name,
            "risk_level": getattr(decision, "risk_level", ""),
            "suggested_action": getattr(decision, "suggested_action", ""),
            "reason": getattr(decision, "reason", ""),
            "should_intervene": bool(getattr(decision, "should_intervene", False)),
            "confidence": getattr(decision, "confidence", 0.0),
        },
        dispatch_observer=False,
    )
    broadcast = str(getattr(decision, "user_facing_broadcast", "") or "").strip()
    if broadcast:
        append_run_event(
            project_id,
            audit_version,
            step_key=runtime_status.get("current_step") or None,
            agent_key="runner_observer_agent",
            agent_name="Runner观察Agent",
            event_kind="runner_broadcast",
            progress_hint=runtime_status.get("progress") or 0,
            message=broadcast,
            meta={
                "stream_layer": "user_facing",
                "source": "runner_observer",
                "provider_name": observer_provider_name,
                "provider_mode": provider_mode or observer_provider_name,
            },
            dispatch_observer=False,
        )


def append_task_trace(task: AuditTask, payload: Dict[str, object]) -> None:
    if task.trace_json:
        try:
            trace = json.loads(task.trace_json)
            if not isinstance(trace, dict):
                trace = {"planner_raw": task.trace_json}
        except Exception:
            trace = {"planner_raw": task.trace_json}
    else:
        trace = {}

    runtime = trace.get("runtime")
    if not isinstance(runtime, list):
        runtime = []
    runtime.append(payload)
    trace["runtime"] = runtime[-30:]
    task.trace_json = json.dumps(trace, ensure_ascii=False)


def set_task_status_batch(
    project_id: str,
    audit_version: int,
    task_ids: List[str],
    status: str,
    *,
    note: str,
    result_ref: Optional[str] = None,
) -> None:
    if not task_ids:
        return

    db = SessionLocal()
    try:
        rows = (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
                AuditTask.id.in_(task_ids),
            )
            .all()
        )
        now = datetime.now().isoformat()
        for task in rows:
            task.status = status
            if result_ref is not None:
                task.result_ref = result_ref
            append_task_trace(
                task,
                {
                    "at": now,
                    "status": status,
                    "note": note,
                },
            )
        db.commit()
    finally:
        db.close()


def mark_running_tasks_failed(project_id: str, audit_version: int, note: str) -> None:
    db = SessionLocal()
    try:
        running_tasks = (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
                AuditTask.status == "running",
            )
            .all()
        )
        if not running_tasks:
            return
        now = datetime.now().isoformat()
        for task in running_tasks:
            task.status = "failed"
            append_task_trace(
                task,
                {
                    "at": now,
                    "status": "failed",
                    "note": note,
                },
            )
        db.commit()
    finally:
        db.close()


def load_tasks(project_id: str, audit_version: int) -> List[AuditTask]:
    db = SessionLocal()
    try:
        return (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
            )
            .order_by(AuditTask.priority.asc(), AuditTask.task_type.asc(), AuditTask.created_at.asc())
            .all()
        )
    finally:
        db.close()


def progress_by_task(completed: int, total: int, *, base: int = 15, span: int = 80) -> int:
    if total <= 0:
        return base
    return base + int(span * completed / total)


def task_group_pairs(tasks: List[AuditTask]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for task in tasks:
        src_raw = (task.source_sheet_no or "").strip()
        tgt_raw = (task.target_sheet_no or "").strip()
        src_key = normalize_sheet_no(src_raw)
        tgt_key = normalize_sheet_no(tgt_raw)
        if not src_key or not tgt_key or src_key == tgt_key:
            continue
        pair_key = tuple(sorted([src_key, tgt_key]))
        if pair_key in seen:
            continue
        seen.add(pair_key)
        pairs.append((src_raw, tgt_raw))
    return pairs


def task_group_source_sheets(tasks: List[AuditTask]) -> List[str]:
    sheets: List[str] = []
    seen: set[str] = set()
    for task in tasks:
        raw = (task.source_sheet_no or "").strip()
        key = normalize_sheet_no(raw)
        if not raw or not key or key in seen:
            continue
        seen.add(key)
        sheets.append(raw)
    return sheets
