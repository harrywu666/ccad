"""项目级 Runner Observer Agent 的共享类型。"""

from __future__ import annotations

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
    available_actions: List[str] = field(default_factory=list)


@dataclass(slots=True)
class RunnerObserverMemory:
    """Observer 在项目长会话里维护的滚动记忆。"""

    project_id: str
    audit_version: int
    project_summary: str = ""
    current_focus: str = ""
    recent_events: List[Dict[str, Any]] = field(default_factory=list)
    intervention_history: List[Dict[str, Any]] = field(default_factory=list)


__all__ = [
    "RunnerObserverDecision",
    "RunnerObserverFeedSnapshot",
    "RunnerObserverMemory",
]
