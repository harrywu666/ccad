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
        "agent_key": "review_kernel_agent",
        "agent_name": "审图内核 Agent",
        "event_kind": "phase_started",
        "progress_hint": 5,
    },
    "context": {
        "agent_key": "review_kernel_agent",
        "agent_name": "审图内核 Agent",
        "event_kind": "phase_progress",
        "progress_hint": 10,
    },
    "relationship_discovery": {
        "agent_key": "worker_skill_agent",
        "agent_name": "节点归属 Skill",
        "event_kind": "phase_progress",
        "progress_hint": 12,
    },
    "task_planning": {
        "agent_key": "review_kernel_agent",
        "agent_name": "审图内核 Agent",
        "event_kind": "phase_progress",
        "progress_hint": 18,
    },
    "index": {
        "agent_key": "worker_skill_agent",
        "agent_name": "索引引用 Skill",
        "event_kind": "phase_progress",
        "progress_hint": 35,
    },
    "dimension": {
        "agent_key": "worker_skill_agent",
        "agent_name": "尺寸一致性 Skill",
        "event_kind": "phase_progress",
        "progress_hint": 60,
    },
    "material": {
        "agent_key": "worker_skill_agent",
        "agent_name": "材料语义一致性 Skill",
        "event_kind": "phase_progress",
        "progress_hint": 78,
    },
    "report": {
        "agent_key": "review_kernel_agent",
        "agent_name": "审图内核 Agent",
        "event_kind": "phase_completed",
        "progress_hint": 95,
    },
}

# review_kernel 直跑模式下关闭运行时观察器链路，仅保留事件落库。
_OBSERVER_TRIGGER_EVENT_KINDS: set[str] = set()

_AGENT_IDENTITY_MAP: Dict[str, Dict[str, str]] = {
    "master_planner_agent": {
        "agent_key": "review_kernel_agent",
        "agent_name": "审图内核 Agent",
    },
    "relationship_review_agent": {
        "agent_key": "worker_skill_agent",
        "agent_name": "节点归属 Skill",
        "skill_id": "node_host_binding",
    },
    "index_review_agent": {
        "agent_key": "worker_skill_agent",
        "agent_name": "索引引用 Skill",
        "skill_id": "index_reference",
    },
    "dimension_review_agent": {
        "agent_key": "worker_skill_agent",
        "agent_name": "尺寸一致性 Skill",
        "skill_id": "elevation_consistency",
    },
    "material_review_agent": {
        "agent_key": "worker_skill_agent",
        "agent_name": "材料语义一致性 Skill",
        "skill_id": "material_semantic_consistency",
    },
    "runner_agent": {
        "agent_key": "finding_synthesizer",
        "agent_name": "结果汇总器",
    },
    "runner_observer_agent": {
        "agent_key": "runtime_observer_agent",
        "agent_name": "运行时观察器",
    },
}

_TASK_STAGE_BY_STEP_KEY: Dict[str, str] = {
    "prepare": "chief_prepare",
    "context": "chief_context",
    "chief_prompt": "chief_prompt_ready",
    "chief_planning": "worker_task_planning",
    "kernel_review": "chief_recheck",
    "relationship_discovery": "worker_relationship_review",
    "index": "worker_skill_execution",
    "dimension": "worker_skill_execution",
    "material": "worker_skill_execution",
    "chief_review": "chief_recheck",
    "report": "finding_synthesized",
    "done": "finding_synthesized",
    "result_stream": "finding_synthesized",
}

_TASK_STAGE_BY_TURN_KIND: Dict[str, str] = {
    "relationship_group_discovery": "worker_relationship_discovery",
    "relationship_candidate_review": "worker_relationship_review",
    "sheet_semantic": "worker_single_sheet_semantic",
    "sheet_semantic_v2": "worker_single_sheet_semantic",
    "pair_compare": "worker_pair_compare",
    "pair_compare_v2": "worker_pair_compare",
    "planning": "worker_task_planning",
    "task_planning": "worker_task_planning",
}

_TASK_STAGE_TITLES: Dict[str, str] = {
    "chief_prepare": "审图内核准备基础数据",
    "chief_context": "审图内核整理图纸上下文",
    "chief_prompt_ready": "审图内核装配审图资源",
    "worker_task_planning": "审图内核分发复核任务",
    "worker_relationship_discovery": "节点归属 Skill 整理候选关系",
    "worker_relationship_review": "节点归属 Skill 复核候选关系",
    "worker_skill_execution": "副审 Skill 执行任务",
    "worker_single_sheet_semantic": "尺寸一致性 Skill 提取单图语义",
    "worker_pair_compare": "尺寸一致性 Skill 执行双图对比",
    "chief_recheck": "审图内核复核副审分歧",
    "finding_synthesized": "审图内核汇总审图结论",
    "runtime_progress": "审图运行中",
}

_SKILL_STAGE_TITLES: Dict[str, Dict[str, str]] = {
    "node_host_binding": {
        "worker_relationship_discovery": "节点归属 Skill 整理候选关系",
        "worker_relationship_review": "节点归属 Skill 复核候选关系",
        "worker_skill_execution": "节点归属 Skill 执行复核",
    },
    "index_reference": {
        "worker_skill_execution": "索引引用 Skill 执行复核",
    },
    "material_semantic_consistency": {
        "worker_skill_execution": "材料语义一致性 Skill 执行复核",
    },
    "elevation_consistency": {
        "worker_skill_execution": "标高一致性 Skill 执行复核",
        "worker_single_sheet_semantic": "标高一致性 Skill 提取单图语义",
        "worker_pair_compare": "标高一致性 Skill 执行双图对比",
    },
    "spatial_consistency": {
        "worker_skill_execution": "空间一致性 Skill 执行复核",
        "worker_single_sheet_semantic": "空间一致性 Skill 提取单图语义",
        "worker_pair_compare": "空间一致性 Skill 执行双图对比",
    },
}

def _resolve_event_defaults(step_key: Optional[str]) -> Dict[str, object]:
    key = (step_key or "").strip()
    if key and key in _STEP_AGENT_DEFAULTS:
        return dict(_STEP_AGENT_DEFAULTS[key])
    return {
        "agent_key": "review_kernel_agent",
        "agent_name": "审图内核 Agent",
        "event_kind": "phase_progress",
        "progress_hint": 0,
    }


def _resolve_pipeline_mode() -> str:
    from services.audit_runtime_service import resolve_runtime_pipeline_mode

    return resolve_runtime_pipeline_mode()


def _infer_task_stage(
    *,
    step_key: Optional[str],
    event_kind: Optional[str],
    meta: Dict[str, object],
) -> str:
    turn_kind = str(meta.get("turn_kind") or "").strip().lower()
    if turn_kind:
        stage = _TASK_STAGE_BY_TURN_KIND.get(turn_kind)
        if stage:
            return stage

    explicit_stage = str(meta.get("task_stage") or "").strip()
    if explicit_stage:
        return explicit_stage

    key = str(step_key or "").strip().lower()
    if key:
        stage = _TASK_STAGE_BY_STEP_KEY.get(key)
        if stage:
            return stage

    normalized_event_kind = str(event_kind or "").strip().lower()
    if normalized_event_kind in {"result_upsert", "result_summary"}:
        return "finding_synthesized"
    if normalized_event_kind in {"runner_turn_needs_review", "master_replan_requested"}:
        return "chief_recheck"
    return "runtime_progress"


def _normalize_agent_identity(
    *,
    agent_key: Optional[str],
    agent_name: Optional[str],
    meta: Dict[str, object],
) -> Dict[str, str]:
    normalized_key = str(agent_key or "").strip()
    mapped = _AGENT_IDENTITY_MAP.get(normalized_key)
    if not mapped:
        return {
            "agent_key": normalized_key,
            "agent_name": str(agent_name or "").strip(),
        }

    result = {
        "agent_key": mapped["agent_key"],
        "agent_name": mapped["agent_name"],
    }
    if mapped.get("skill_id") and not str(meta.get("skill_id") or "").strip():
        meta["skill_id"] = mapped["skill_id"]
    return result


def _resolve_task_stage_title(task_stage: str, skill_id: str | None = None) -> str | None:
    normalized_stage = str(task_stage or "").strip()
    if not normalized_stage:
        return None
    normalized_skill = str(skill_id or "").strip()
    if normalized_skill:
        title = _SKILL_STAGE_TITLES.get(normalized_skill, {}).get(normalized_stage)
        if title:
            return title
    return _TASK_STAGE_TITLES.get(normalized_stage)


def _normalize_runtime_message(
    *,
    message: str,
    identity: Dict[str, str],
    meta: Dict[str, object],
) -> str:
    text = str(message or "").strip()
    if not text:
        return text

    event_kind = str(meta.get("event_kind") or "").strip()
    source = str(meta.get("source") or "").strip()
    preserve_source_agent_name = (
        event_kind == "runner_broadcast"
        and source == "agent_status_report"
    )

    replacements = {"Runner观察Agent": "运行时观察器"}
    if not preserve_source_agent_name:
        replacements.update(
            {
                "总控规划Agent": identity["agent_name"],
                "关系审查Agent": identity["agent_name"],
                "索引审查Agent": identity["agent_name"],
                "尺寸审查Agent": identity["agent_name"],
                "材料审查Agent": identity["agent_name"],
            }
        )
    for before, after in replacements.items():
        text = text.replace(before, after)

    task_stage = str(meta.get("task_stage") or "").strip()
    skill_id = str(meta.get("skill_id") or "").strip()
    stage_title = _resolve_task_stage_title(task_stage, skill_id)

    if stage_title and text in {
        "规划中",
        "主审路径：主审 Agent 正在整理这次审图的基础信息",
        "主审 Agent 正在继续推进当前审图步骤",
        "审图内核路径：审图内核 Agent 正在整理这次审图的基础信息",
        "审图内核 Agent 正在继续推进当前审图步骤",
    }:
        return stage_title

    if stage_title and str(meta.get("event_kind") or "").strip() == "heartbeat":
        return f"{stage_title}，后台仍在继续推进"

    return text


def _enrich_runtime_meta(
    *,
    step_key: Optional[str],
    agent_key: Optional[str],
    agent_name: Optional[str],
    event_kind: Optional[str],
    meta: Optional[Dict[str, object]],
) -> tuple[Dict[str, str], Dict[str, object]]:
    payload = dict(meta or {})
    identity = _normalize_agent_identity(
        agent_key=agent_key,
        agent_name=agent_name,
        meta=payload,
    )
    payload.setdefault("pipeline_mode", _resolve_pipeline_mode())
    payload.setdefault(
        "planner_source",
        "review_kernel"
        if payload.get("pipeline_mode") in {"chief_review", "review_kernel_v1"}
        else "legacy_stage_planner",
    )
    payload.setdefault(
        "prompt_source",
        "agent_skill"
        if str(payload.get("skill_id") or "").strip()
        else (
            "review_kernel"
            if identity["agent_key"] in {"chief_review_agent", "review_kernel_agent", "finding_synthesizer", "runtime_observer_agent"}
            else "legacy_stage_template"
        ),
    )
    payload.setdefault(
        "skill_mode",
        "worker_skill" if str(payload.get("skill_id") or "").strip() else "none",
    )
    payload.setdefault(
        "compat_mode",
        "legacy_template_compat"
        if payload.get("prompt_source") == "legacy_stage_template"
        else "native_agent_runtime",
    )
    session_key = str(payload.get("session_key") or payload.get("subsession_key") or "").strip()
    if session_key:
        payload["session_key"] = session_key
    evidence_selection_policy = str(payload.get("evidence_selection_policy") or "").strip()
    if evidence_selection_policy:
        payload["evidence_selection_policy"] = evidence_selection_policy
    payload["task_stage"] = _infer_task_stage(
        step_key=step_key,
        event_kind=event_kind,
        meta=payload,
    )
    return identity, payload


def normalize_event_for_display(
    *,
    step_key: Optional[str],
    agent_key: Optional[str],
    agent_name: Optional[str],
    event_kind: Optional[str],
    message: str,
    meta: Optional[Dict[str, object]] = None,
) -> tuple[Dict[str, str], Dict[str, object], str]:
    identity, payload = _enrich_runtime_meta(
        step_key=step_key,
        agent_key=agent_key,
        agent_name=agent_name,
        event_kind=event_kind,
        meta=meta,
    )
    normalized_message = _normalize_runtime_message(
        message=message,
        identity=identity,
        meta={**payload, "event_kind": str(event_kind or "").strip()},
    )
    return identity, payload, normalized_message


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
    dispatch_observer: bool = False,
) -> None:
    db = SessionLocal()
    try:
        defaults = _resolve_event_defaults(step_key)
        identity, enriched_meta, normalized_message = normalize_event_for_display(
            step_key=step_key,
            agent_key=(agent_key or str(defaults["agent_key"])),
            agent_name=(agent_name or str(defaults["agent_name"])),
            event_kind=(event_kind or str(defaults["event_kind"])),
            message=message,
            meta=meta,
        )
        event = AuditRunEvent(
            project_id=project_id,
            audit_version=audit_version,
            level=(level or "info").strip() or "info",
            step_key=(step_key or "").strip() or None,
            agent_key=identity["agent_key"].strip() or None,
            agent_name=identity["agent_name"].strip() or None,
            event_kind=(event_kind or str(defaults["event_kind"])).strip() or None,
            progress_hint=(
                int(progress_hint)
                if progress_hint is not None
                else int(defaults["progress_hint"])
            ),
            message=normalized_message,
            meta_json=json.dumps(enriched_meta, ensure_ascii=False),
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
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
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
    issue_to_raw: Dict[str, Dict[str, Any]] = {}
    for raw_item in raw_items:
        issue_id = str(raw_item.get("id") or "").strip()
        if issue_id:
            issue_to_raw[issue_id] = raw_item
    for row in grouped_items:
        for issue_id in row.get("issue_ids") or []:
            issue_to_row[str(issue_id)] = row
    return grouped_items, counts, issue_to_row, issue_to_raw


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
        _, counts, issue_to_row, issue_to_raw = _build_grouped_result_snapshot(
            db,
            project_id,
            audit_version,
        )
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
            message="结果汇总器 已向报告追加一条问题",
            meta={
                "delta_kind": "upsert",
                "view": "grouped",
                "row": row,
                "raw_rows": [
                    issue_to_raw[str(item)]
                    for item in (row.get("issue_ids") or [issue_id])
                    if issue_to_raw.get(str(item))
                ],
                "counts": counts,
                "source_issue_ids": row.get("issue_ids") or [issue_id],
            },
            dispatch_observer=False,
        )


def append_result_summary_event(project_id: str, audit_version: int) -> None:
    db = SessionLocal()
    try:
        _, counts, _, _ = _build_grouped_result_snapshot(db, project_id, audit_version)
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
        message=f"结果汇总器 已同步报告汇总：当前共 {counts['total']} 条问题",
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
    del project_id, audit_version, step_key, progress_hint, agent_key, agent_name, report
    return None


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
    del project_id, audit_version, agent_key
    return False


def _restart_master_agent(
    project_id: str,
    audit_version: int,
    *,
    runtime_status: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    from services.audit_runtime_service import restart_master_agent_async

    restart_result = restart_master_agent_async(project_id, audit_version)
    append_run_event(
        project_id,
        audit_version,
        step_key=runtime_status.get("current_step") or None,
        agent_key="runner_observer_agent",
        agent_name="Runner观察Agent",
        event_kind="runner_master_recovery_requested",
        progress_hint=runtime_status.get("progress") or 0,
        message="Runner 正在重启审图内核",
        meta={
            "stream_layer": "internal_master_recovery",
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
        message="Runner 已完成重启，等待内核继续推进",
        meta={
            "stream_layer": "internal_master_recovery",
            "recent_events_seen": len(recent_events),
            "restart_result": restart_result,
        },
        dispatch_observer=False,
    )
    return {
        "restarted": bool(restart_result.get("restarted")),
        "memory": {},
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
    del project_id, audit_version, runtime_status, recent_events, decision
    return None


def _dispatch_runner_observer(
    project_id: str,
    audit_version: int,
    *,
    event_kind: Optional[str],
) -> None:
    del project_id, audit_version, event_kind
    return


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
