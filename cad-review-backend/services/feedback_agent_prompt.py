"""误报反馈 Agent 的提示资产与用户提示构造。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from models import AuditResult, FeedbackThread


_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts" / "feedback_agent"


def _read_prompt_file(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def _read_prompt_file_with_fallback(*names: str) -> str:
    for name in names:
        path = _PROMPT_DIR / name
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"feedback agent prompt file not found: {names}")


def load_feedback_agent_prompt() -> str:
    return _read_prompt_file_with_fallback("AGENT.md", "Agent.md")


def load_feedback_agent_soul_prompt() -> str:
    return _read_prompt_file_with_fallback("SOUL.md", "soul.md")


def load_feedback_agent_user_prompt_template() -> str:
    return _read_prompt_file_with_fallback("PROMPT.md", "prompt.md")


def build_feedback_agent_system_prompt() -> str:
    return f"{load_feedback_agent_prompt()}\n\n---\n\n{load_feedback_agent_soul_prompt()}".strip()


def build_feedback_agent_user_prompt(
    *,
    thread: FeedbackThread,
    audit_result: AuditResult,
    recent_messages: List[Dict[str, Any]],
    similar_cases: List[Dict[str, Any]],
) -> str:
    payload = {
        "thread": {
            "id": thread.id,
            "status": thread.status,
            "learning_decision": thread.learning_decision,
            "audit_version": thread.audit_version,
            "source_agent": thread.source_agent,
            "rule_id": thread.rule_id,
            "issue_type": thread.issue_type,
        },
        "audit_result": {
            "id": audit_result.id,
            "type": audit_result.type,
            "severity": audit_result.severity,
            "rule_id": audit_result.rule_id,
            "finding_type": audit_result.finding_type,
            "finding_status": audit_result.finding_status,
            "source_agent": audit_result.source_agent,
            "confidence": audit_result.confidence,
            "sheet_no_a": audit_result.sheet_no_a,
            "sheet_no_b": audit_result.sheet_no_b,
            "location": audit_result.location,
            "description": audit_result.description,
            "feedback_status": audit_result.feedback_status,
            "feedback_note": audit_result.feedback_note,
        },
        "recent_messages": recent_messages[-8:],
        "similar_cases": similar_cases,
    }

    template = load_feedback_agent_user_prompt_template()
    return template.replace("{{payload_json}}", json.dumps(payload, ensure_ascii=False))


__all__ = [
    "build_feedback_agent_system_prompt",
    "build_feedback_agent_user_prompt",
    "load_feedback_agent_prompt",
    "load_feedback_agent_soul_prompt",
    "load_feedback_agent_user_prompt_template",
]
