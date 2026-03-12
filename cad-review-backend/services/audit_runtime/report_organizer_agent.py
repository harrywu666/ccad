"""把终审通过的问题整理成 Markdown 报告块。"""

from __future__ import annotations

from typing import Any


def _read_field(payload: Any, key: str, default: Any = "") -> Any:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _render_issue_block(index: int, accepted_decision: Any) -> str:
    assignment = _read_field(accepted_decision, "assignment")
    worker_result = _read_field(accepted_decision, "worker_result")
    final_review_decision = _read_field(accepted_decision, "final_review_decision")

    source_sheet_no = str(_read_field(assignment, "source_sheet_no", "") or "").strip()
    target_sheet_nos = list(_read_field(assignment, "target_sheet_nos", []) or [])
    task_title = str(_read_field(assignment, "task_title", "") or "").strip()
    review_intent = str(_read_field(assignment, "review_intent", "") or "").strip()
    summary = str(_read_field(worker_result, "summary", "") or "").strip()
    rationale = str(_read_field(final_review_decision, "rationale", "") or "").strip()
    confidence = float(_read_field(worker_result, "confidence", 0.0) or 0.0)
    target_text = "、".join(str(item).strip() for item in target_sheet_nos if str(item).strip()) or "未提供目标图"

    lines = [
        f"## 问题 {index}",
        f"- 标题：{summary or task_title or review_intent or '待补充标题'}",
        f"- 图纸范围：{source_sheet_no or 'UNKNOWN'} -> {target_text}",
        f"- 审查意图：{review_intent or 'unknown'}",
        f"- 描述：{summary or task_title or '待补充描述'}",
        f"- 终审意见：{rationale or '终审已通过'}",
        f"- 置信度：{confidence:.2f}",
    ]
    return "\n".join(lines)


def run_report_organizer_agent(*, accepted_decisions: list[Any]) -> str:
    blocks = [_render_issue_block(index, item) for index, item in enumerate(accepted_decisions, start=1)]
    return "\n\n".join(block for block in blocks if block).strip()


__all__ = ["run_report_organizer_agent"]
