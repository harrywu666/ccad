"""Runner Observer Agent 的现场整理层。"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from services.audit_runtime.runner_observer_types import RunnerObserverFeedSnapshot


_DEFAULT_ACTIONS = [
    "observe_only",
    "broadcast_update",
    "cancel_turn",
    "restart_subsession",
    "rerun_current_step",
    "mark_needs_review",
]


def _build_risk_signals(recent_events: List[Dict[str, Any]]) -> List[str]:
    signals: List[str] = []
    for event in recent_events:
        event_kind = str(event.get("event_kind") or "").strip()
        if event_kind == "runner_turn_retrying":
            signals.append("turn_retrying")
        elif event_kind == "runner_turn_needs_review":
            signals.append("needs_review")
        elif event_kind == "output_validation_failed":
            signals.append("output_unstable")
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
        "runner_turn_needs_review_count": counter.get("runner_turn_needs_review", 0),
        "output_unstable_streak": _output_unstable_streak(recent_events),
    }


def _build_intervention_hint(risk_summary: Dict[str, Any]) -> str:
    failed_count = int(risk_summary.get("output_validation_failed_count") or 0)
    unstable_streak = int(risk_summary.get("output_unstable_streak") or 0)
    retry_count = int(risk_summary.get("runner_turn_retrying_count") or 0)
    if failed_count >= 2 or unstable_streak >= 2:
        return (
            "最近同类输出不稳已经连续出现。不要继续只做 observe_only，"
            "需要在 broadcast_update、restart_subsession、mark_needs_review 之间认真权衡。"
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
    return RunnerObserverFeedSnapshot(
        project_id=project_id,
        audit_version=int(audit_version),
        current_step=current_step,
        runtime_status=dict(runtime_status),
        recent_events=recent_items,
        current_risk_signals=_build_risk_signals(recent_items),
        risk_summary=risk_summary,
        intervention_hint=_build_intervention_hint(risk_summary),
        available_actions=list(_DEFAULT_ACTIONS),
    )


__all__ = ["build_observer_snapshot"]
