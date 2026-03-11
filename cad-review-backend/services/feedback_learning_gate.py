"""误报反馈学习门禁服务。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FeedbackLearningGateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    learning_decision: Literal[
        "accepted_for_learning",
        "rejected_for_learning",
        "needs_human_review",
        "record_only",
    ]
    reason_code: str
    reason_text: str
    evidence_score: float
    similar_case_count: int
    reusability_score: float


def evaluate_learning_gate(
    *,
    agent_status: str,
    evidence_score: float,
    similar_case_count: int,
    reusability_score: float,
) -> FeedbackLearningGateDecision:
    evidence = round(float(evidence_score or 0.0), 3)
    similar = max(0, int(similar_case_count or 0))
    reusable = round(float(reusability_score or 0.0), 3)

    if agent_status != "resolved_incorrect":
        return FeedbackLearningGateDecision(
            learning_decision="rejected_for_learning",
            reason_code="agent_not_confirmed_incorrect",
            reason_text="反馈判定还没有确认这条问题是误报，先不进入学习。",
            evidence_score=evidence,
            similar_case_count=similar,
            reusability_score=reusable,
        )

    if evidence >= 0.85 and similar >= 2 and reusable >= 0.7:
        return FeedbackLearningGateDecision(
            learning_decision="accepted_for_learning",
            reason_code="reusable_pattern_confirmed",
            reason_text="证据较强，且已有相似案例支撑，适合进入学习。",
            evidence_score=evidence,
            similar_case_count=similar,
            reusability_score=reusable,
        )

    if evidence >= 0.6 and similar >= 1 and reusable >= 0.65:
        return FeedbackLearningGateDecision(
            learning_decision="needs_human_review",
            reason_code="important_but_uncertain_pattern",
            reason_text="这条反馈看起来有复用价值，但当前还不够稳，建议人工复核后再决定是否学习。",
            evidence_score=evidence,
            similar_case_count=similar,
            reusability_score=reusable,
        )

    if evidence >= 0.75 and reusable < 0.5:
        return FeedbackLearningGateDecision(
            learning_decision="record_only",
            reason_code="project_specific_exception",
            reason_text="反馈大概率成立，但更像项目特例，先记录，不进入学习。",
            evidence_score=evidence,
            similar_case_count=similar,
            reusability_score=reusable,
        )

    return FeedbackLearningGateDecision(
        learning_decision="rejected_for_learning",
        reason_code="insufficient_learning_value",
        reason_text="当前证据或复用价值不足，先不进入学习。",
        evidence_score=evidence,
        similar_case_count=similar,
        reusability_score=reusable,
    )
