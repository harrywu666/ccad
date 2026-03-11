"""误报反馈判定 Agent 的结构化类型。"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class FeedbackAgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "resolved_incorrect",
        "resolved_not_incorrect",
        "agent_needs_user_input",
        "escalated_to_human",
    ]
    user_reply: str
    summary: str
    confidence: float
    reason_codes: list[str] = Field(default_factory=list)
    needs_learning_gate: bool
    suggested_learning_decision: Literal[
        "pending",
        "accepted_for_learning",
        "rejected_for_learning",
        "record_only",
        "needs_human_review",
    ] = "pending"
    follow_up_question: Optional[str] = None
    evidence_gaps: list[str] = Field(default_factory=list)
