"""Runner Observer Agent 的现场整理层。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from services.audit_runtime.master_agent_health import detect_master_behavior_anomaly
from services.audit_runtime.runner_observer_types import RunnerObserverFeedSnapshot


_DEFAULT_ACTIONS = [
    "observe_only",
    "broadcast_update",
    "restart_subsession",
    "restart_master_agent",
]


def _build_risk_signals(recent_events: List[Dict[str, Any]]) -> List[str]:
    signals: List[str] = []
    for event in recent_events:
        event_kind = str(event.get("event_kind") or "").strip()
        if event_kind == "runner_turn_retrying":
            signals.append("turn_retrying")
        elif event_kind in {"runner_turn_deferred", "runner_turn_needs_review"}:
            signals.append("deferred")
        elif event_kind == "output_validation_failed":
            signals.append("output_unstable")
        elif event_kind == "runner_help_requested":
            signals.append("agent_help_requested")
        elif event_kind == "master_replan_requested":
            signals.append("master_behavior_abnormal")
    return signals


def _output_unstable_streak(recent_events: List[Dict[str, Any]]) -> int:
    streak = 0
    for event in reversed(recent_events):
        event_kind = str(event.get("event_kind") or "").strip()
        if event_kind == "output_validation_failed":
            streak += 1
            continue
        if event_kind in {"runner_broadcast", "provider_stream_delta", "runner_observer_decision"}:
            continue
        break
    return streak


def _build_risk_summary(recent_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    counter = Counter(str(event.get("event_kind") or "").strip() for event in recent_events)
    return {
        "output_validation_failed_count": counter.get("output_validation_failed", 0),
        "output_repair_succeeded_count": counter.get("output_repair_succeeded", 0),
        "runner_turn_retrying_count": counter.get("runner_turn_retrying", 0),
        "runner_turn_deferred_count": counter.get("runner_turn_deferred", 0)
        + counter.get("runner_turn_needs_review", 0),
        "agent_status_reported_count": counter.get("agent_status_reported", 0),
        "agent_help_requested_count": counter.get("runner_help_requested", 0),
        "agent_help_resolved_count": counter.get("runner_help_resolved", 0),
        "output_unstable_streak": _output_unstable_streak(recent_events),
        "master_replan_requested_count": counter.get("master_replan_requested", 0),
    }


def _extract_active_agent_reports(recent_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for event in recent_events:
        if str(event.get("event_kind") or "").strip() != "agent_status_reported":
            continue
        meta = event.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        reports.append(
            {
                "agent_key": str(event.get("agent_key") or "").strip(),
                "agent_name": str(event.get("agent_name") or "").strip(),
                "message": str(event.get("message") or "").strip(),
                "runner_help_request": str(meta.get("runner_help_request") or "").strip(),
                "next_recommended_action": str(meta.get("next_recommended_action") or "").strip(),
                "blocking_issues": list(meta.get("blocking_issues") or []),
                "agent_confidence": meta.get("agent_confidence"),
            }
        )
    return reports[-3:]


def _build_intervention_hint(
    risk_summary: Dict[str, Any],
    active_agent_reports: List[Dict[str, Any]],
) -> str:
    failed_count = int(risk_summary.get("output_validation_failed_count") or 0)
    unstable_streak = int(risk_summary.get("output_unstable_streak") or 0)
    retry_count = int(risk_summary.get("runner_turn_retrying_count") or 0)
    help_requested_count = int(risk_summary.get("agent_help_requested_count") or 0)
    master_replan_count = int(risk_summary.get("master_replan_requested_count") or 0)
    if master_replan_count >= 3:
        return "总控已经连续多次重排同一批任务，这不像正常整理，更像是在原地打转。你需要认真考虑 restart_master_agent。"
    if help_requested_count >= 1 or active_agent_reports:
        return (
            "下属审查Agent 已主动求助。不要把这当成普通噪音，"
            "你需要优先判断当前帮助动作是否足够，还是要继续升级处理。"
        )
    if failed_count >= 2 or unstable_streak >= 2:
        return (
            "最近同类输出不稳已经连续出现。不要继续只做 observe_only，"
            "需要在 broadcast_update、restart_subsession 之间认真权衡。"
        )
    if retry_count >= 1:
        return "当前步骤已经进入重试阶段，除非你确认现场恢复，否则不要继续机械观察。"
    return "当前以继续观察为主，但一旦同类问题重复出现，需要及时升级动作。"


def build_observer_snapshot(
    *,
    project_id: str,
    audit_version: int,
    runtime_status: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
) -> RunnerObserverFeedSnapshot:
    current_step = str(runtime_status.get("current_step") or "").strip()
    recent_items = list(recent_events)
    risk_summary = _build_risk_summary(recent_items)
    active_agent_reports = _extract_active_agent_reports(recent_items)
    master_health = detect_master_behavior_anomaly(
        recent_events=recent_items,
        runtime_status=runtime_status,
    )
    if master_health.get("is_anomalous"):
        risk_summary["master_behavior_anomaly"] = master_health
    return RunnerObserverFeedSnapshot(
        project_id=project_id,
        audit_version=int(audit_version),
        current_step=current_step,
        runtime_status=dict(runtime_status),
        recent_events=recent_items,
        active_agent_reports=active_agent_reports,
        current_risk_signals=_build_risk_signals(recent_items)
        + ([str(master_health.get("signal") or "").strip()] if master_health.get("is_anomalous") else []),
        risk_summary=risk_summary,
        intervention_hint=_build_intervention_hint(risk_summary, active_agent_reports),
        available_actions=list(_DEFAULT_ACTIONS),
    )


__all__ = ["build_observer_snapshot"]
