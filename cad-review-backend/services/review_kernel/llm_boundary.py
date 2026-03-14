"""LLM 介入边界约束。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


LLM_STAGE_WEAK_ASSIST = "weak_assist"
LLM_STAGE_DISAMBIGUATION = "disambiguation"
LLM_STAGE_REPORT_WRITING = "report_writing"

ALLOWED_STAGES = {
    LLM_STAGE_WEAK_ASSIST,
    LLM_STAGE_DISAMBIGUATION,
    LLM_STAGE_REPORT_WRITING,
}


@dataclass(frozen=True)
class LlmBoundaryDecision:
    stage: str
    allowed: bool
    reason: str


def _estimate_tokens(payload: dict[str, Any]) -> int:
    return max(1, int(len(json.dumps(payload, ensure_ascii=False)) / 4))


def _has_dimension_triple(payload: dict[str, Any]) -> bool:
    evidence = payload.get("dimension_evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if (
            item.get("display_value") is not None
            and item.get("measured_value") is not None
            and item.get("computed_value") is not None
        ):
            return True
    return False


def _contains_raw_dump(payload: dict[str, Any]) -> bool:
    raw_keys = {"raw_layer", "raw_entities", "documents", "full_document_dump"}
    return any(key in payload for key in raw_keys)


def check_llm_boundary(
    *,
    stage: str,
    context_slice: dict[str, Any] | None,
    max_tokens: int = 8000,
) -> LlmBoundaryDecision:
    normalized_stage = str(stage or "").strip()
    if normalized_stage not in ALLOWED_STAGES:
        return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="unsupported_stage")

    if not isinstance(context_slice, dict):
        return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="missing_context_slice")
    payload = context_slice.get("payload")
    if not isinstance(payload, dict):
        return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="invalid_payload")
    if _contains_raw_dump(payload):
        return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="raw_dump_forbidden")
    if _estimate_tokens(payload) > max_tokens:
        return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="slice_over_budget")

    logical_sheet = payload.get("logical_sheet")
    review_view = payload.get("review_view")
    if not isinstance(logical_sheet, dict) or not logical_sheet:
        return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="logical_sheet_not_ready")
    if not isinstance(review_view, dict) or not review_view:
        return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="review_view_not_ready")

    if normalized_stage == LLM_STAGE_WEAK_ASSIST:
        return LlmBoundaryDecision(stage=normalized_stage, allowed=True, reason="ok")

    if normalized_stage == LLM_STAGE_DISAMBIGUATION:
        candidate_relations = payload.get("candidate_relations")
        if not isinstance(candidate_relations, list) or not candidate_relations:
            return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="candidate_relations_missing")
        if not _has_dimension_triple(payload):
            return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="dimension_truth_not_ready")
        return LlmBoundaryDecision(stage=normalized_stage, allowed=True, reason="ok")

    if normalized_stage == LLM_STAGE_REPORT_WRITING:
        issues = payload.get("issues")
        if not isinstance(issues, list) or not issues:
            return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="issues_missing")
        return LlmBoundaryDecision(stage=normalized_stage, allowed=True, reason="ok")

    return LlmBoundaryDecision(stage=normalized_stage, allowed=False, reason="unsupported_stage")


def confidence_upper_bound_from_slice(context_slice: dict[str, Any] | None) -> float:
    if not isinstance(context_slice, dict):
        return 0.5
    payload = context_slice.get("payload")
    if not isinstance(payload, dict):
        return 0.5

    caps: list[float] = [1.0]
    evidence = payload.get("dimension_evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            score = item.get("confidence")
            if isinstance(score, (int, float)):
                caps.append(float(score))

    degradation = payload.get("degradation_notices")
    if isinstance(degradation, list):
        for notice in degradation:
            if not isinstance(notice, dict):
                continue
            severity = str(notice.get("severity") or "").strip().lower()
            if severity in {"high", "critical"}:
                caps.append(0.55)
            elif severity in {"medium"}:
                caps.append(0.7)
            elif severity in {"low"}:
                caps.append(0.82)

    return max(0.3, min(caps))
