"""主审与副审共享任务卡结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HypothesisCard:
    id: str
    topic: str
    objective: str
    source_sheet_no: str
    target_sheet_nos: list[str] = field(default_factory=list)
    priority: float = 0.5
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerTaskCard:
    id: str
    hypothesis_id: str
    worker_kind: str
    objective: str
    source_sheet_no: str
    target_sheet_nos: list[str] = field(default_factory=list)
    anchor_hint: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerResultCard:
    task_id: str
    hypothesis_id: str
    worker_kind: str
    status: str
    confidence: float
    summary: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    escalate_to_chief: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "HypothesisCard",
    "WorkerTaskCard",
    "WorkerResultCard",
]
