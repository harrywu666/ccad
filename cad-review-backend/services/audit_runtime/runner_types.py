"""项目级审图 Runner 的共享类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class ProviderStreamEvent:
    """Provider 吐出的统一流式事件。"""

    event_kind: str
    text: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunnerTurnRequest:
    """一次业务 Agent 调用 Runner 的输入。"""

    agent_key: str
    turn_kind: str
    system_prompt: str
    user_prompt: str
    images: List[bytes] = field(default_factory=list)
    temperature: float = 0.1
    max_tokens: int = 65536
    agent_name: str = ""
    step_key: str = ""
    progress_hint: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunnerTurnResult:
    """Runner 返回给业务 Agent 的统一结果。"""

    provider_name: str
    output: Any
    status: str = "ok"
    raw_output: str = ""
    subsession_key: Optional[str] = None
    repair_attempts: int = 0
    error: Optional[str] = None
    events: List[ProviderStreamEvent] = field(default_factory=list)


@dataclass(slots=True)
class RunnerSubsession:
    """项目级 Runner 内部的业务子会话。"""

    project_id: str
    audit_version: int
    agent_key: str
    session_key: str
    shared_context: Dict[str, Any]
    retry_count: int = 0
    session_started: bool = False
    current_turn_status: str = "idle"
    turn_started_at: Optional[float] = None
    last_delta_at: Optional[float] = None
    last_progress_at: Optional[float] = None
    current_phase: str = "idle"
    stall_reason: Optional[str] = None
    last_broadcast: Optional[str] = None
    output_history: List[str] = field(default_factory=list)


__all__ = [
    "ProviderStreamEvent",
    "RunnerTurnRequest",
    "RunnerTurnResult",
    "RunnerSubsession",
]
