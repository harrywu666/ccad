from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.feedback_agent_prompt import (  # type: ignore[attr-defined]
    build_feedback_agent_system_prompt,
    build_feedback_agent_user_prompt,
)


class DummyThread:
    id = "thread-1"
    status = "agent_reviewing"
    learning_decision = "pending"
    audit_version = 3
    source_agent = "index_review_agent"
    rule_id = "index_alias_rule"
    issue_type = "index"


class DummyAuditResult:
    id = "result-1"
    type = "index"
    severity = "error"
    rule_id = "index_alias_rule"
    finding_type = "missing_ref"
    finding_status = "confirmed"
    source_agent = "index_review_agent"
    confidence = 0.66
    sheet_no_a = "A1.01"
    sheet_no_b = "A6.01"
    location = "索引1"
    description = "索引指向疑似不一致"
    feedback_status = "none"
    feedback_note = None


def test_feedback_agent_system_prompt_includes_agent_and_soul():
    prompt = build_feedback_agent_system_prompt()

    assert "误报反馈 Agent" in prompt
    assert "审慎裁判" in prompt
    assert "只返回一个 JSON 对象" in prompt


def test_feedback_agent_user_prompt_contains_schema_and_context():
    prompt = build_feedback_agent_user_prompt(
        thread=DummyThread(),
        audit_result=DummyAuditResult(),
        recent_messages=[{"role": "user", "content": "这是误报"}],
        similar_cases=[{"id": "case-1", "rule_id": "index_alias_rule", "issue_type": "index"}],
    )

    assert '"status":"resolved_incorrect|resolved_not_incorrect|agent_needs_user_input|escalated_to_human"' in prompt
    assert "similar_cases" in prompt
    assert "A1.01" in prompt
    assert "index_alias_rule" in prompt
