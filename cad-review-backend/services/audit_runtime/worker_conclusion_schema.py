"""副审 markdown 结论与证据包契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


GroundingStatus = Literal["grounded", "weak", "missing"]
ResultKind = Literal["issue", "non_issue", "relationship_signal"]


class WorkerEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="allow")

    assignment_id: str | None = None
    task_id: str | None = None
    worker_kind: str | None = None
    rule_id: str | None = None
    evidence_pack_id: str | None = None
    review_round: int | None = None
    summary: str = ""
    result_kind: ResultKind = "issue"
    grounding_status: GroundingStatus
    anchors: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    raw_skill_outputs: list[dict[str, Any]] = Field(default_factory=list)


class WorkerConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown_conclusion: str = Field(min_length=1)
    evidence_bundle: WorkerEvidenceBundle


__all__ = ["GroundingStatus", "ResultKind", "WorkerEvidenceBundle", "WorkerConclusion"]
