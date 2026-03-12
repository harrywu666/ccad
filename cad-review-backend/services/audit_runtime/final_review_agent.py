"""终审 Agent 的最小规则实现。"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.audit_runtime.final_review_prompt_assembler import assemble_final_review_prompt
from services.audit_runtime.finding_schema import GroundingRequiredError, validate_grounded_evidence_json


class FinalReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected", "needs_more_evidence", "redispatch"]
    rationale: str = Field(min_length=1)
    source_assignment_id: str = Field(min_length=1)
    evidence_pack_id: str = Field(min_length=1)
    requires_grounding: bool = True


def run_final_review_agent(*, assignment, worker_result) -> FinalReviewDecision:  # noqa: ANN001
    assemble_final_review_prompt(assignment=assignment, worker_result=worker_result)
    assignment_id = str(
        getattr(assignment, "assignment_id", None)
        or (getattr(worker_result, "evidence_bundle", {}) or {}).get("assignment_id")
        or getattr(worker_result, "task_id", "")
    ).strip()
    evidence_bundle = dict(getattr(worker_result, "evidence_bundle", {}) or {})
    evidence_pack_id = str(
        evidence_bundle.get("evidence_pack_id")
        or getattr(worker_result, "meta", {}).get("evidence_pack_id")
        or "chief_review_pack"
    ).strip() or "chief_review_pack"
    payload = json.dumps(
        {
            "evidence_bundle": evidence_bundle,
        },
        ensure_ascii=False,
    )
    try:
        validate_grounded_evidence_json(payload)
        grounded = True
    except GroundingRequiredError:
        grounded = False

    status = str(getattr(worker_result, "status", "") or "").strip().lower()
    confidence = float(getattr(worker_result, "confidence", 0.0) or 0.0)

    if not grounded:
        return FinalReviewDecision(
            decision="needs_more_evidence",
            rationale="缺少可定位的 grounded anchors，不能直接进入最终通过态",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    if status in {"rejected", "dismissed"}:
        return FinalReviewDecision(
            decision="rejected",
            rationale="副审结论已明确否定，不进入最终结果",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    if status in {"needs_review", "conflict"}:
        return FinalReviewDecision(
            decision="redispatch",
            rationale="副审仍需主审补派或补证据",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    if status == "confirmed" and confidence >= 0.8:
        return FinalReviewDecision(
            decision="accepted",
            rationale="副审结论和定位证据都达标，可进入最终结果",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    return FinalReviewDecision(
        decision="needs_more_evidence",
        rationale="结论或证据还不够稳定，需要补证据",
        source_assignment_id=assignment_id,
        evidence_pack_id=evidence_pack_id,
    )


__all__ = ["FinalReviewDecision", "run_final_review_agent"]
