"""总控 Agent 健康度判断。"""

from __future__ import annotations

from typing import Any, Dict, List


MASTER_REPLAN_ANOMALY_THRESHOLD = 3


def _consecutive_master_replans(recent_events: List[Dict[str, Any]]) -> int:
    streak = 0
    for event in reversed(recent_events):
        event_kind = str(event.get("event_kind") or "").strip()
        agent_key = str(event.get("agent_key") or "").strip()
        if agent_key != "master_planner_agent":
            continue
        if event_kind == "master_replan_requested":
            streak += 1
            continue
        break
    return streak


def detect_master_behavior_anomaly(
    *,
    recent_events: List[Dict[str, Any]],
    runtime_status: Dict[str, Any],
) -> Dict[str, Any]:
    replan_streak = _consecutive_master_replans(recent_events)
    if replan_streak >= MASTER_REPLAN_ANOMALY_THRESHOLD:
        return {
            "is_anomalous": True,
            "reason": "master_replan_loop",
            "signal": "master_behavior_abnormal",
            "replan_streak": replan_streak,
            "current_step": str(runtime_status.get("current_step") or "").strip(),
        }
    return {
        "is_anomalous": False,
        "reason": "",
        "signal": "",
        "replan_streak": replan_streak,
        "current_step": str(runtime_status.get("current_step") or "").strip(),
    }


__all__ = [
    "MASTER_REPLAN_ANOMALY_THRESHOLD",
    "detect_master_behavior_anomaly",
]
