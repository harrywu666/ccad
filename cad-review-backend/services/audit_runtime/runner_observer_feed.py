"""Runner Observer Agent 的现场整理层。"""

from __future__ import annotations

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


def build_observer_snapshot(
    *,
    project_id: str,
    audit_version: int,
    runtime_status: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
) -> RunnerObserverFeedSnapshot:
    current_step = str(runtime_status.get("current_step") or "").strip()
    return RunnerObserverFeedSnapshot(
        project_id=project_id,
        audit_version=int(audit_version),
        current_step=current_step,
        runtime_status=dict(runtime_status),
        recent_events=list(recent_events),
        current_risk_signals=_build_risk_signals(list(recent_events)),
        available_actions=list(_DEFAULT_ACTIONS),
    )


__all__ = ["build_observer_snapshot"]
