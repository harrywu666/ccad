"""终审 Agent 的最小规则实现。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.audit_runtime.final_review_prompt_assembler import assemble_final_review_prompt
from services.audit_runtime.finding_schema import GroundingRequiredError, validate_grounded_evidence_json

logger = logging.getLogger(__name__)


class FinalReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected", "needs_more_evidence", "redispatch"]
    decision_source: Literal["llm", "rule_fallback"] = "rule_fallback"
    rationale: str = Field(min_length=1)
    source_assignment_id: str = Field(min_length=1)
    evidence_pack_id: str = Field(min_length=1)
    requires_grounding: bool = True


def _provider_mode() -> str:
    raw = str(os.getenv("KIMI_PROVIDER", "official") or "official").strip().lower()
    if raw in {"openrouter", "open_router"}:
        return "openrouter"
    if raw in {"official", "moonshot", "openai"}:
        return "official"
    return "code"


def _provider_key_available() -> bool:
    provider = _provider_mode()
    if provider == "openrouter":
        return bool(str(os.getenv("OPENROUTER_API_KEY", "")).strip())
    if provider == "official":
        return bool(
            str(os.getenv("KIMI_OFFICIAL_API_KEY", "")).strip()
            or str(os.getenv("MOONSHOT_API_KEY", "")).strip()
        )
    return bool(str(os.getenv("KIMI_CODE_API_KEY", "")).strip())


def _llm_final_review_enabled() -> bool:
    raw = str(os.getenv("AUDIT_FINAL_REVIEW_LLM_MODE", "auto") or "auto").strip().lower()
    if raw in {"off", "false", "0", "no", "disabled"}:
        return False
    if raw in {"on", "true", "1", "yes", "always"}:
        return True
    return _provider_key_available()


def _call_final_review_llm(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    from services.ai_service import call_kimi

    payload = asyncio.run(
        call_kimi(
            system_prompt,
            user_prompt,
            temperature=0.1,
            max_tokens=1024,
        )
    )
    if not isinstance(payload, dict):
        raise ValueError(f"终审 LLM 返回不是对象: {type(payload).__name__}")
    return payload


def _normalize_llm_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"true", "1", "yes", "on"}:
            return True
        if raw in {"false", "0", "no", "off"}:
            return False
    return default


def _build_decision_from_llm_payload(
    *,
    payload: dict[str, Any],
    assignment_id: str,
    evidence_pack_id: str,
) -> FinalReviewDecision:
    decision = str(payload.get("decision") or "").strip().lower()
    rationale = str(payload.get("rationale") or "").strip()
    requires_grounding = _normalize_llm_bool(payload.get("requires_grounding"), default=True)
    if decision not in {"accepted", "rejected", "needs_more_evidence", "redispatch"}:
        raise ValueError(f"终审 LLM 返回非法 decision: {decision!r}")
    if not rationale:
        raise ValueError("终审 LLM 缺少 rationale")
    return FinalReviewDecision(
        decision=decision,
        decision_source="llm",
        rationale=rationale,
        source_assignment_id=assignment_id,
        evidence_pack_id=evidence_pack_id,
        requires_grounding=requires_grounding,
    )


def _build_rule_based_decision(
    *,
    assignment_id: str,
    evidence_pack_id: str,
    grounded: bool,
    status: str,
    confidence: float,
) -> FinalReviewDecision:
    if not grounded:
        return FinalReviewDecision(
            decision="needs_more_evidence",
            decision_source="rule_fallback",
            rationale="缺少可定位的 grounded anchors，不能直接进入最终通过态",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    if status in {"rejected", "dismissed"}:
        return FinalReviewDecision(
            decision="rejected",
            decision_source="rule_fallback",
            rationale="副审结论已明确否定，不进入最终结果",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    if status in {"needs_review", "conflict"}:
        return FinalReviewDecision(
            decision="redispatch",
            decision_source="rule_fallback",
            rationale="副审仍需主审补派或补证据",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    if status == "confirmed" and confidence >= 0.8:
        return FinalReviewDecision(
            decision="accepted",
            decision_source="rule_fallback",
            rationale="副审结论和定位证据都达标，可进入最终结果",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    return FinalReviewDecision(
        decision="needs_more_evidence",
        decision_source="rule_fallback",
        rationale="结论或证据还不够稳定，需要补证据",
        source_assignment_id=assignment_id,
        evidence_pack_id=evidence_pack_id,
    )


def run_final_review_agent(*, assignment, worker_result) -> FinalReviewDecision:  # noqa: ANN001
    prompt_bundle = assemble_final_review_prompt(assignment=assignment, worker_result=worker_result)
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
    result_kind = str(evidence_bundle.get("result_kind") or "").strip().lower()

    if result_kind == "relationship_signal":
        return FinalReviewDecision(
            decision="rejected",
            decision_source="rule_fallback",
            rationale="副审返回的是关系线索，不是正式施工图问题",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )
    if result_kind == "non_issue":
        return FinalReviewDecision(
            decision="rejected",
            decision_source="rule_fallback",
            rationale="副审已明确未发现问题，不进入最终结果",
            source_assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
        )

    # 硬约束：没有 grounded anchors 时，终审必须走规则兜底，不能由 LLM 决策来源覆盖。
    if not grounded:
        return _build_rule_based_decision(
            assignment_id=assignment_id,
            evidence_pack_id=evidence_pack_id,
            grounded=grounded,
            status=status,
            confidence=confidence,
        )

    llm_decision: FinalReviewDecision | None = None
    if _llm_final_review_enabled():
        try:
            llm_payload = _call_final_review_llm(
                prompt_bundle["system_prompt"],
                prompt_bundle["user_prompt"],
            )
            llm_decision = _build_decision_from_llm_payload(
                payload=llm_payload,
                assignment_id=assignment_id,
                evidence_pack_id=evidence_pack_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("终审 LLM 调用失败，回退规则判断: %s", exc)

    if llm_decision is not None:
        # 兜底护栏：LLM 不能绕过定位证据硬约束
        if llm_decision.decision == "accepted" and not grounded:
            return FinalReviewDecision(
                decision="needs_more_evidence",
                decision_source="rule_fallback",
                rationale="终审判定为通过，但缺少 grounded anchors，已退回补证据",
                source_assignment_id=assignment_id,
                evidence_pack_id=evidence_pack_id,
                requires_grounding=True,
            )
        return llm_decision

    return _build_rule_based_decision(
        assignment_id=assignment_id,
        evidence_pack_id=evidence_pack_id,
        grounded=grounded,
        status=status,
        confidence=confidence,
    )


__all__ = ["FinalReviewDecision", "run_final_review_agent"]
