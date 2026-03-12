"""审核运行态更新与任务状态迁移。"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from domain.sheet_normalization import normalize_sheet_no
from database import SessionLocal
from models import AuditResult, AuditRun, AuditRunEvent, AuditTask, Project
from services.audit_runtime.providers.factory import normalize_provider_mode
from services.audit_runtime.result_view import (
    group_results_for_view,
    serialize_audit_result,
    summarize_grouped_counts,
)


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
    "runner_turn_deferred",
    "runner_turn_needs_review",
    "master_replan_requested",
    "master_recovery_exhausted",
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


def _build_grouped_result_snapshot(
    db, project_id: str, audit_version: int  # noqa: ANN001
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Dict[str, Any]]]:
    rows = (
        db.query(AuditResult)
        .filter(
            AuditResult.project_id == project_id,
            AuditResult.audit_version == audit_version,
        )
        .order_by(AuditResult.created_at.asc())
        .all()
    )
    raw_items = [serialize_audit_result(item) for item in rows]
    grouped_items = group_results_for_view(raw_items)
    counts = summarize_grouped_counts(grouped_items)
    issue_to_row: Dict[str, Dict[str, Any]] = {}
    for row in grouped_items:
        for issue_id in row.get("issue_ids") or []:
            issue_to_row[str(issue_id)] = row
    return grouped_items, counts, issue_to_row


def append_result_upsert_events(
    project_id: str,
    audit_version: int,
    *,
    issue_ids: List[str],
) -> None:
    normalized_issue_ids = [str(item).strip() for item in issue_ids if str(item).strip()]
    if not normalized_issue_ids:
        return

    db = SessionLocal()
    try:
        _, counts, issue_to_row = _build_grouped_result_snapshot(db, project_id, audit_version)
    finally:
        db.close()

    emitted_row_ids: set[str] = set()
    for issue_id in normalized_issue_ids:
        row = issue_to_row.get(issue_id)
        if not row:
            continue
        row_id = str(row.get("id") or "").strip()
        if not row_id or row_id in emitted_row_ids:
            continue
        emitted_row_ids.add(row_id)
        append_run_event(
            project_id,
            audit_version,
            level="info",
            step_key="result_stream",
            agent_key="runner_agent",
            agent_name="Runner Agent",
            event_kind="result_upsert",
            progress_hint=None,
            message="Runner Agent 已向报告追加一条问题",
            meta={
                "delta_kind": "upsert",
                "view": "grouped",
                "row": row,
                "counts": counts,
                "source_issue_ids": row.get("issue_ids") or [issue_id],
            },
            dispatch_observer=False,
        )


def append_result_summary_event(project_id: str, audit_version: int) -> None:
    db = SessionLocal()
    try:
        _, counts, _ = _build_grouped_result_snapshot(db, project_id, audit_version)
    finally:
        db.close()

    append_run_event(
        project_id,
        audit_version,
        level="info",
        step_key="result_stream",
        agent_key="runner_agent",
        agent_name="Runner Agent",
        event_kind="result_summary",
        progress_hint=None,
        message=f"Runner Agent 已同步报告汇总：当前共 {counts['total']} 条问题",
        meta={
            "delta_kind": "summary",
            "view": "grouped",
            "counts": counts,
        },
        dispatch_observer=False,
    )


def append_agent_status_report(
    project_id: str,
    audit_version: int,
    *,
    step_key: Optional[str],
    agent_key: str,
    agent_name: str,
    progress_hint: Optional[int],
    report,  # noqa: ANN001
    dispatch_observer: bool = False,
) -> None:
    from services.audit_runtime.runner_broadcasts import (
        build_runner_broadcast_from_agent_report,
    )

    meta = {
        "stream_layer": "internal_agent_report",
        "report_scope": "internal_only",
        "batch_summary": str(getattr(report, "batch_summary", "") or "").strip(),
        "confirmed_count": len(list(getattr(report, "confirmed_findings", None) or [])),
        "suspected_count": len(list(getattr(report, "suspected_findings", None) or [])),
        "blocking_issues": list(getattr(report, "blocking_issues", None) or []),
        "runner_help_request": str(getattr(report, "runner_help_request", "") or "").strip(),
        "agent_confidence": float(getattr(report, "agent_confidence", 0.0) or 0.0),
        "next_recommended_action": str(getattr(report, "next_recommended_action", "") or "").strip(),
    }
    append_run_event(
        project_id,
        audit_version,
        step_key=step_key,
        agent_key=agent_key,
        agent_name=agent_name,
        event_kind="agent_status_reported",
        progress_hint=progress_hint,
        message=meta["batch_summary"] or f"{agent_name} 已提交一份内部工作汇报",
        meta=meta,
        dispatch_observer=dispatch_observer,
    )
    append_run_event(
        project_id,
        audit_version,
        step_key=step_key,
        agent_key="runner_observer_agent",
        agent_name="Runner观察Agent",
        event_kind="runner_broadcast",
        progress_hint=progress_hint,
        message=build_runner_broadcast_from_agent_report(agent_name, report),
        meta={
            "stream_layer": "user_facing",
            "report_scope": "progress_only",
            "source": "agent_status_report",
            "source_agent_key": agent_key,
        },
        dispatch_observer=False,
    )
    _execute_agent_help_request(
        project_id,
        audit_version,
        step_key=step_key,
        progress_hint=progress_hint,
        agent_key=agent_key,
        agent_name=agent_name,
        report=report,
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


def _rewrite_agent_help_request(requested_action: str) -> Tuple[str, str]:
    normalized = str(requested_action or "").strip()
    if normalized == "mark_needs_review":
        return "restart_subsession", "mid_run_needs_review_blocked"
    if normalized == "rerun_current_batch":
        return "restart_subsession", "batch_rerun_mapped_to_restart_subsession"
    return normalized, ""


def _execute_agent_help_request(
    project_id: str,
    audit_version: int,
    *,
    step_key: Optional[str],
    progress_hint: Optional[int],
    agent_key: str,
    agent_name: str,
    report,  # noqa: ANN001
) -> Optional[Dict[str, Any]]:
    requested_action_name = str(getattr(report, "runner_help_request", "") or "").strip()
    blocking_issues = list(getattr(report, "blocking_issues", None) or [])
    if not requested_action_name or not blocking_issues:
        return None

    from services.audit_runtime.runner_action_gate import RunnerActionGate

    action_name, rewrite_reason = _rewrite_agent_help_request(requested_action_name)
    append_run_event(
        project_id,
        audit_version,
        step_key=step_key,
        agent_key="runner_observer_agent",
        agent_name="Runner观察Agent",
        event_kind="runner_help_requested",
        progress_hint=progress_hint,
        message=f"Runner 已收到 {agent_name} 的求助请求，正在尝试处理",
        meta={
            "stream_layer": "internal_agent_help",
            "report_scope": "internal_only",
            "source_agent_key": agent_key,
            "requested_action_name": requested_action_name,
            "action_name": action_name,
            "rewrite_reason": rewrite_reason,
            "blocking_issues": blocking_issues,
        },
        dispatch_observer=False,
    )

    gate = RunnerActionGate(project_root=".")
    result = gate.execute(
        action_name,
        context={
            "broadcast_message": f"Runner 正在协助 {agent_name} 恢复稳定",
            "restart_subsession": lambda: _restart_runner_subsession(
                project_id,
                audit_version,
                agent_key=agent_key,
            ),
        },
    )
    append_run_event(
        project_id,
        audit_version,
        step_key=step_key,
        agent_key="runner_observer_agent",
        agent_name="Runner观察Agent",
        event_kind="runner_help_resolved",
        progress_hint=progress_hint,
        message=f"Runner 已处理 {agent_name} 的求助请求：{result.get('action_name') or action_name}",
        meta={
            "stream_layer": "internal_agent_help",
            "report_scope": "internal_only",
            "source_agent_key": agent_key,
            "requested_action_name": requested_action_name,
            "action_name": result.get("action_name") or action_name,
            "allowed": bool(result.get("allowed")),
            "executed": bool(result.get("executed")),
            "result": result.get("result"),
            "reason": result.get("reason", ""),
            "rewrite_reason": rewrite_reason,
        },
        dispatch_observer=False,
    )
    return result


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
                    raw_provider_mode = (
                        str(meta.get("provider_mode") or "").strip()
                        or str(meta.get("provider_name") or "").strip()
                        or None
                    )
                    provider_mode = (
                        normalize_provider_mode(raw_provider_mode)
                        if raw_provider_mode
                        else None
                    )
                if current_step and progress is not None and provider_mode:
                    break
            return {
                "status": "running",
                "current_step": current_step,
                "progress": progress,
                "provider_mode": provider_mode,
                "has_persisted_run": False,
            }
        return {
            "status": getattr(run, "status", None),
            "current_step": getattr(run, "current_step", None),
            "progress": getattr(run, "progress", None),
                "provider_mode": normalize_provider_mode(getattr(run, "provider_mode", None)),
            "has_persisted_run": True,
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


def _find_target_agent_key(recent_events: List[Dict[str, Any]]) -> Optional[str]:
    for item in reversed(recent_events):
        agent_key = str(item.get("agent_key") or "").strip()
        if not agent_key or agent_key == "runner_observer_agent":
            continue
        return agent_key
    return None


def _restart_runner_subsession(
    project_id: str,
    audit_version: int,
    *,
    agent_key: Optional[str],
) -> bool:
    if not agent_key:
        return False

    from services.audit_runtime.agent_runner import ProjectAuditAgentRunner

    runner = ProjectAuditAgentRunner.get_existing(project_id, audit_version=audit_version)
    if runner is None or getattr(runner, "provider", None) is None:
        return False

    subsession = runner.get_existing_subsession(agent_key)
    if subsession is None:
        return False

    restarted = bool(_run_async(runner.provider.restart_subsession(subsession)))
    if restarted:
        subsession.session_started = False
        subsession.current_turn_status = "idle"
        subsession.current_phase = "observer_restart_pending"
        subsession.stall_reason = "observer_restart_subsession"
        subsession.output_history.clear()
        subsession.last_broadcast = None
    return restarted


def _restart_master_agent(
    project_id: str,
    audit_version: int,
    *,
    runtime_status: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    from dataclasses import asdict

    from services.audit_runtime.project_recovery_memory import load_project_recovery_memory
    from services.audit_runtime_service import restart_master_agent_async

    memory = load_project_recovery_memory(project_id, audit_version=audit_version)
    restart_result = restart_master_agent_async(project_id, audit_version)
    append_run_event(
        project_id,
        audit_version,
        step_key=runtime_status.get("current_step") or None,
        agent_key="runner_observer_agent",
        agent_name="Runner观察Agent",
        event_kind="runner_master_recovery_requested",
        progress_hint=runtime_status.get("progress") or 0,
        message="Runner 正在带着项目级记忆重启总控Agent",
        meta={
            "stream_layer": "internal_master_recovery",
            "memory": asdict(memory),
            "recent_events_seen": len(recent_events),
            "restart_result": restart_result,
        },
        dispatch_observer=False,
    )
    append_run_event(
        project_id,
        audit_version,
        step_key=runtime_status.get("current_step") or None,
        agent_key="runner_observer_agent",
        agent_name="Runner观察Agent",
        event_kind="runner_master_recovery_succeeded",
        progress_hint=runtime_status.get("progress") or 0,
        message="Runner 已把项目级记忆交回总控Agent，后续会继续盯它是否恢复推进",
        meta={
            "stream_layer": "internal_master_recovery",
            "memory": asdict(memory),
            "recent_events_seen": len(recent_events),
            "restart_result": restart_result,
        },
        dispatch_observer=False,
    )
    return {
        "restarted": bool(restart_result.get("restarted")),
        "memory": asdict(memory),
        "restart_result": restart_result,
    }


def _rewrite_observer_action(
    requested_action: str,
    *,
    recent_events: List[Dict[str, Any]],
) -> Tuple[str, str]:
    normalized = str(requested_action or "").strip()
    if normalized != "mark_needs_review":
        return normalized, ""
    if _find_target_agent_key(recent_events):
        return "restart_subsession", "mid_run_needs_review_blocked"
    return "broadcast_update", "mid_run_needs_review_blocked"


def _execute_observer_action(
    project_id: str,
    audit_version: int,
    *,
    runtime_status: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
    decision,
) -> Optional[Dict[str, Any]]:  # noqa: ANN001
    if not bool(getattr(decision, "should_intervene", False)):
        return None

    from services.audit_runtime.runner_action_gate import RunnerActionGate

    reason = str(getattr(decision, "reason", "") or "").strip()
    gate = RunnerActionGate(project_root=".")
    requested_action_name = str(getattr(decision, "suggested_action", "") or "").strip()
    action_name, rewrite_reason = _rewrite_observer_action(
        requested_action_name,
        recent_events=recent_events,
    )
    result = gate.execute(
        action_name,
        context={
            "broadcast_message": str(getattr(decision, "user_facing_broadcast", "") or "").strip(),
            "restart_subsession": lambda: _restart_runner_subsession(
                project_id,
                audit_version,
                agent_key=_find_target_agent_key(recent_events),
            ),
            "restart_master_agent": lambda: _restart_master_agent(
                project_id,
                audit_version,
                runtime_status=runtime_status,
                recent_events=recent_events,
            ),
        },
    )
    action_label = result.get("action_name") or action_name or "observe_only"
    executed = bool(result.get("executed"))
    action_message = (
        f"Runner 已执行观察动作：{action_label}"
        if executed
        else f"Runner 暂未执行观察动作：{action_label}"
    )
    append_run_event(
        project_id,
        audit_version,
        step_key=runtime_status.get("current_step") or None,
        agent_key="runner_observer_agent",
        agent_name="Runner观察Agent",
        event_kind="runner_observer_action",
        progress_hint=runtime_status.get("progress") or 0,
        message=action_message,
        meta={
            "stream_layer": "observer_action",
            "action_name": result.get("action_name"),
            "requested_action_name": requested_action_name or action_name,
            "allowed": bool(result.get("allowed")),
            "executed": bool(result.get("executed")),
            "result": result.get("result"),
            "reason": result.get("reason", ""),
            "rewrite_reason": rewrite_reason,
        },
        dispatch_observer=False,
    )
    return result


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
    raw_provider_mode = str(runtime_status.get("provider_mode") or "").strip() or None
    provider_mode = normalize_provider_mode(raw_provider_mode) if raw_provider_mode else None
    use_active_provider = bool(runtime_status.get("has_persisted_run"))
    observer = ProjectRunnerObserverSession.get_or_create(
        project_id,
        audit_version=audit_version,
        provider_mode=provider_mode,
        provider=build_runner_provider(requested_mode=provider_mode)
        if (use_active_provider and provider_mode)
        else _PassiveObserverProvider(),
    )
    if hasattr(observer, "should_observe") and not observer.should_observe():
        return
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
    _execute_observer_action(
        project_id,
        audit_version,
        runtime_status=runtime_status,
        recent_events=recent_events,
        decision=decision,
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
