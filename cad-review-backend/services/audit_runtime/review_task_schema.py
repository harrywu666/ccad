"""审图内核/副审共享的最小任务卡结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewAssignment(BaseModel):
    """审图内核派给单个副审卡的正式任务契约。"""

    model_config = ConfigDict(extra="forbid")

    assignment_id: str = Field(min_length=1)
    review_intent: str = Field(min_length=1)
    source_sheet_no: str = Field(min_length=1)
    target_sheet_nos: list[str]
    task_title: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    expected_evidence_types: list[str] = Field(min_length=1)
    priority: float = Field(ge=0.0, le=1.0)
    dispatch_reason: str = Field(min_length=1)

    @field_validator(
        "assignment_id",
        "review_intent",
        "source_sheet_no",
        "task_title",
        "dispatch_reason",
        mode="before",
    )
    @classmethod
    def _validate_required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @field_validator("target_sheet_nos", mode="before")
    @classmethod
    def _validate_targets(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("target_sheet_nos must be a list")
        normalized = [str(item or "").strip() for item in value]
        if not normalized or len(normalized) > 2:
            raise ValueError("target_sheet_nos must contain 1-2 sheets")
        if any(not item for item in normalized):
            raise ValueError("target_sheet_nos items must not be empty")
        return normalized

    @field_validator("acceptance_criteria", "expected_evidence_types", mode="before")
    @classmethod
    def _validate_non_empty_text_list(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("value must be a list")
        normalized = [str(item or "").strip() for item in value]
        if not normalized or any(not item for item in normalized):
            raise ValueError("list items must not be empty")
        return normalized


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
    skill_id: str = ""
    session_key: str = ""
    evidence_selection_policy: str = ""
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
    markdown_conclusion: str = ""
    evidence_bundle: dict[str, Any] = field(default_factory=dict)
    escalate_to_chief: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


__all__ = ["ReviewAssignment", "HypothesisCard", "WorkerTaskCard", "WorkerResultCard"]
