"""主审增量派单停止/等待/继续规则。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from services.audit_runtime.review_task_schema import ReviewAssignment


class DispatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_dispatch: bool
    should_wait: bool
    should_stop: bool
    reason: str


def evaluate_dispatch_state(
    *,
    pending_assignments: list[ReviewAssignment] | list[dict[str, Any]],
    active_worker_count: int,
    final_review_pending_count: int,
    has_new_directions: bool,
) -> DispatchDecision:
    if pending_assignments:
        return DispatchDecision(
            should_dispatch=True,
            should_wait=False,
            should_stop=False,
            reason="pending_assignments_ready",
        )
    if active_worker_count > 0 or final_review_pending_count > 0:
        return DispatchDecision(
            should_dispatch=False,
            should_wait=True,
            should_stop=False,
            reason="waiting_for_running_or_review_queue",
        )
    if has_new_directions:
        return DispatchDecision(
            should_dispatch=True,
            should_wait=False,
            should_stop=False,
            reason="new_directions_available",
        )
    return DispatchDecision(
        should_dispatch=False,
        should_wait=False,
        should_stop=True,
        reason="no_pending_workers_or_new_directions",
    )


__all__ = ["DispatchDecision", "evaluate_dispatch_state"]
