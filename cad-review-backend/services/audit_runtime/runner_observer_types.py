"""项目级 Runner Observer Agent 的共享类型。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class RunnerObserverDecision:
    """Observer 对当前项目现场的一次结构化判断。"""

    summary: str
    risk_level: str
    suggested_action: str
    reason: str
    should_intervene: bool
    confidence: float
    user_facing_broadcast: str = ""


@dataclass(slots=True)
class RunnerObserverFeedSnapshot:
    """喂给 Observer 的当前项目现场摘要。"""

    project_id: str
    audit_version: int
    current_step: str = ""
    runtime_status: Dict[str, Any] = field(default_factory=dict)
    recent_events: List[Dict[str, Any]] = field(default_factory=list)
    current_risk_signals: List[str] = field(default_factory=list)
    risk_summary: Dict[str, Any] = field(default_factory=dict)
    intervention_hint: str = ""
    available_actions: List[str] = field(default_factory=list)


@dataclass(slots=True)
class RunnerObserverMemory:
    """Observer 在项目长会话里维护的滚动记忆。"""

    project_id: str
    audit_version: int
    project_summary: str = ""
    current_focus: str = ""
    recent_events: List[Dict[str, Any]] = field(default_factory=list)
    recent_decisions: List[Dict[str, Any]] = field(default_factory=list)
    intervention_history: List[Dict[str, Any]] = field(default_factory=list)


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty_observer_output")
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        payload = json.loads(raw[start : end + 1])
        if isinstance(payload, dict):
            return payload
    raise ValueError("invalid_observer_output")


def observer_decision_from_text(text: str) -> RunnerObserverDecision:
    payload = _extract_json_object(text)
    return RunnerObserverDecision(
        summary=str(payload.get("summary") or "").strip(),
        risk_level=str(payload.get("risk_level") or "unknown").strip() or "unknown",
        suggested_action=str(payload.get("suggested_action") or "observe_only").strip() or "observe_only",
        reason=str(payload.get("reason") or "").strip(),
        should_intervene=bool(payload.get("should_intervene", False)),
        confidence=float(payload.get("confidence") or 0.0),
        user_facing_broadcast=str(payload.get("user_facing_broadcast") or "").strip(),
    )


__all__ = [
    "RunnerObserverDecision",
    "RunnerObserverFeedSnapshot",
    "RunnerObserverMemory",
    "observer_decision_from_text",
]
