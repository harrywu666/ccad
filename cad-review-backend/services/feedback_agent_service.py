"""误报反馈判定服务。"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from models import AuditResult, FeedbackLearningRecord, FeedbackThread
from services.audit_runtime.output_guard import guard_output
from services.audit_runtime.providers.factory import build_runner_provider
from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest
from services.feedback_agent_prompt import (
    build_feedback_agent_system_prompt,
    build_feedback_agent_user_prompt,
)
from services.feedback_agent_types import FeedbackAgentDecision


logger = logging.getLogger(__name__)


_GENERIC_CLAIMS = {
    "误报",
    "这是误报",
    "这条是误报",
    "错了",
    "不对",
}

_DETAIL_KEYWORDS = (
    "别名",
    "简称",
    "一直叫",
    "习惯叫",
    "项目里",
    "目录里",
    "同一张图",
    "alias",
)


def query_similar_feedback_cases(
    db: Session,
    *,
    rule_id: str | None,
    issue_type: str | None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    if not rule_id or not issue_type:
        return []

    rows = (
        db.query(FeedbackLearningRecord)
        .filter(
            FeedbackLearningRecord.rule_id == rule_id,
            FeedbackLearningRecord.issue_type == issue_type,
            FeedbackLearningRecord.decision.in_(["accepted_for_learning", "accepted"]),
        )
        .all()
    )

    ranked = sorted(
        rows,
        key=lambda item: (
            float(item.evidence_score or 0.0),
            item.created_at or datetime.min,
        ),
        reverse=True,
    )[:limit]
    return [
        {
            "id": row.id,
            "thread_id": row.thread_id,
            "rule_id": row.rule_id,
            "issue_type": row.issue_type,
            "decision": row.decision,
            "evidence_score": float(row.evidence_score or 0.0),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in ranked
    ]


def _feedback_agent_mode() -> str:
    raw = str(os.getenv("FEEDBACK_AGENT_MODE", "llm") or "llm").strip().lower()
    if raw in {"rule", "rules", "heuristic"}:
        return "rule"
    return "hybrid"


def _feedback_agent_max_tokens() -> int:
    raw = str(os.getenv("FEEDBACK_AGENT_MAX_TOKENS", "1200") or "1200").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1200
    return max(256, min(value, 4096))


def _feedback_agent_provider_mode() -> str:
    raw = str(os.getenv("FEEDBACK_AGENT_PROVIDER", "api") or "api").strip().lower()
    if raw in {"sdk", "kimi_sdk"}:
        return "sdk"
    if raw in {"api", "kimi_api", "openrouter", "openrouter_api"}:
        return "api"
    if raw == "cli":
        return "cli"
    if raw == "auto":
        return "auto"
    return "api"


def _build_feedback_agent_provider():
    return build_runner_provider(requested_mode=_feedback_agent_provider_mode())


def _normalize_decision(decision: FeedbackAgentDecision) -> FeedbackAgentDecision:
    confidence = float(decision.confidence or 0.0)
    decision.confidence = max(0.0, min(1.0, confidence))
    if decision.status == "agent_needs_user_input" and not decision.follow_up_question:
        decision.follow_up_question = decision.user_reply
    if decision.status != "agent_needs_user_input":
        decision.follow_up_question = None
    return decision


def decide_feedback_thread_by_rules(
    *,
    thread: FeedbackThread,
    audit_result: AuditResult,
    recent_messages: List[Dict[str, Any]],
    similar_cases: List[Dict[str, Any]],
) -> FeedbackAgentDecision:
    latest_user_message = ""
    for item in reversed(recent_messages):
        if str(item.get("role") or "").strip() == "user":
            latest_user_message = str(item.get("content") or "").strip()
            break

    normalized = latest_user_message.strip().lower()
    confidence = float(audit_result.confidence or 0.0)
    has_detail = bool(
        latest_user_message
        and (
            any(keyword in latest_user_message for keyword in _DETAIL_KEYWORDS)
            or any(char.isdigit() for char in latest_user_message)
        )
    )
    is_generic_claim = normalized in _GENERIC_CLAIMS or len(latest_user_message) <= 8

    if not latest_user_message or (is_generic_claim and not has_detail and not similar_cases and confidence < 0.75):
        follow_up = "你可以补一句这张图在项目里的常用叫法、别名，或为什么你判断它其实指向同一张图吗？"
        return _normalize_decision(FeedbackAgentDecision(
            status="agent_needs_user_input",
            user_reply="我先收到了这条误报反馈，但当前信息还不够，我需要再确认一下项目里的实际叫法。",
            summary="用户反馈过于笼统，暂时无法直接判断是否为误报。",
            confidence=round(max(0.35, confidence), 2),
            reason_codes=["insufficient_context"],
            needs_learning_gate=False,
            suggested_learning_decision="pending",
            follow_up_question=follow_up,
            evidence_gaps=["project_alias_or_naming_context"],
        ))

    if has_detail or similar_cases:
        matched = len(similar_cases)
        reply = "我看了这条问题和你补充的说法，当前更像是项目内叫法/别名导致的误判。先按误报候选处理。"
        if matched:
            reply += f" 我还命中了 {matched} 条相同规则和问题类型的已采纳案例。"
        return _normalize_decision(FeedbackAgentDecision(
            status="resolved_incorrect",
            user_reply=reply,
            summary="这条反馈更像是命名别名或项目私有叫法导致的误报。",
            confidence=round(max(0.78, confidence), 2),
            reason_codes=["alias_or_project_naming_pattern"],
            needs_learning_gate=True,
            suggested_learning_decision="pending",
            follow_up_question=None,
            evidence_gaps=[],
        ))

    return _normalize_decision(FeedbackAgentDecision(
        status="resolved_not_incorrect",
        user_reply="我复核了当前信息，但还看不出足够证据支持这是误报，先维持原判断。",
        summary="当前上下文不足以推翻原始问题判定。",
        confidence=round(max(0.6, confidence), 2),
        reason_codes=["insufficient_counter_evidence"],
        needs_learning_gate=False,
        suggested_learning_decision="rejected_for_learning",
        follow_up_question=None,
        evidence_gaps=[],
    ))


def _decide_feedback_thread_by_llm(
    *,
    thread: FeedbackThread,
    audit_result: AuditResult,
    recent_messages: List[Dict[str, Any]],
    similar_cases: List[Dict[str, Any]],
    image_payloads: List[bytes],
) -> FeedbackAgentDecision:
    system_prompt = build_feedback_agent_system_prompt()
    user_prompt = build_feedback_agent_user_prompt(
        thread=thread,
        audit_result=audit_result,
        recent_messages=recent_messages,
        similar_cases=similar_cases,
    )
    provider = _build_feedback_agent_provider()
    request = RunnerTurnRequest(
        agent_key="feedback_agent",
        agent_name="误报反馈Agent",
        step_key="feedback_thread",
        progress_hint=100,
        turn_kind="feedback_thread_review",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        images=image_payloads,
        temperature=0.0,
        max_tokens=_feedback_agent_max_tokens(),
        meta={
            "thread_id": thread.id,
            "audit_result_id": audit_result.id,
            "provider_mode": _feedback_agent_provider_mode(),
        },
    )
    subsession = RunnerSubsession(
        project_id=thread.project_id,
        audit_version=int(thread.audit_version or audit_result.audit_version or 0),
        agent_key="feedback_agent",
        session_key=f"feedback-thread:{thread.id}",
        shared_context={
            "thread_id": thread.id,
            "audit_result_id": audit_result.id,
        },
    )
    result = asyncio.run(provider.run_once(request, subsession))
    payload = result.output
    if payload is None:
        payload = guard_output(result.raw_output)
    return _normalize_decision(FeedbackAgentDecision.model_validate(payload))


def decide_feedback_thread(
    *,
    thread: FeedbackThread,
    audit_result: AuditResult,
    recent_messages: List[Dict[str, Any]],
    similar_cases: List[Dict[str, Any]],
    image_payloads: List[bytes] | None = None,
) -> FeedbackAgentDecision:
    mode = _feedback_agent_mode()
    if mode == "rule":
        return decide_feedback_thread_by_rules(
            thread=thread,
            audit_result=audit_result,
            recent_messages=recent_messages,
            similar_cases=similar_cases,
        )
    return _decide_feedback_thread_by_llm(
        thread=thread,
        audit_result=audit_result,
        recent_messages=recent_messages,
        similar_cases=similar_cases,
        image_payloads=list(image_payloads or []),
    )
