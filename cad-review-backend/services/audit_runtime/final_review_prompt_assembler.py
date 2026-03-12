"""终审阶段的最小提示词装配。"""

from __future__ import annotations

from typing import Any


def assemble_final_review_prompt(*, assignment, worker_result) -> dict[str, Any]:  # noqa: ANN001
    return {
        "system_prompt": "你是终审 Agent，只负责判断副审结论是否成立、证据是否够落图。",
        "user_prompt": (
            f"任务：{getattr(assignment, 'task_title', '')}\n"
            f"副审结论：{getattr(worker_result, 'markdown_conclusion', '')}\n"
            f"证据包：{getattr(worker_result, 'evidence_bundle', {})}\n"
        ),
    }


__all__ = ["assemble_final_review_prompt"]
