"""终审阶段的最小提示词装配。"""

from __future__ import annotations

import json
from typing import Any


def assemble_final_review_prompt(*, assignment, worker_result) -> dict[str, Any]:  # noqa: ANN001
    evidence_bundle = getattr(worker_result, "evidence_bundle", {}) or {}
    payload = {
        "task_title": getattr(assignment, "task_title", ""),
        "review_intent": getattr(assignment, "review_intent", ""),
        "source_sheet_no": getattr(assignment, "source_sheet_no", ""),
        "target_sheet_nos": list(getattr(assignment, "target_sheet_nos", []) or []),
        "worker_status": getattr(worker_result, "status", ""),
        "worker_confidence": getattr(worker_result, "confidence", 0.0),
        "worker_summary": getattr(worker_result, "summary", ""),
        "worker_markdown_conclusion": getattr(worker_result, "markdown_conclusion", ""),
        "result_kind": evidence_bundle.get("result_kind", ""),
        "evidence_bundle": evidence_bundle,
    }
    return {
        "system_prompt": (
            "你是终审 Agent。"
            "你要先判断副审返回的是正式问题、不是问题，还是只是关系线索。"
            "只有正式问题候选才允许进入最终结果；关系线索和普通引用确认不能进入最终问题。"
            "同时要判断证据是否足够落图。"
            "你只能输出 JSON，不要输出任何额外文本。"
            'JSON 格式固定为 {"decision":"accepted|rejected|needs_more_evidence|redispatch","rationale":"...","requires_grounding":true|false}。'
        ),
        "user_prompt": (
            "请基于下面的副审结果做终审判断。\n"
            "判断规则：\n"
            "1) 关系线索不是正式问题；\n"
            "2) 没有可定位锚点时，不能 accepted；\n"
            "3) 副审结论不稳定时可给 redispatch；\n"
            "4) 证据不足时给 needs_more_evidence。\n"
            "输入数据(JSON)：\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        ),
    }


__all__ = ["assemble_final_review_prompt"]
