"""原生副审执行入口。"""

from __future__ import annotations

from services.audit_runtime.review_task_schema import WorkerResultCard, WorkerTaskCard
from services.audit_runtime.worker_skill_registry import (
    get_worker_skill_executor,
    has_registered_worker_skill,
)


def has_native_review_worker(worker_kind: str) -> bool:
    return has_registered_worker_skill(worker_kind)


async def run_native_review_worker(
    *,
    task: WorkerTaskCard,
    db,
) -> WorkerResultCard | None:  # noqa: ANN001
    worker_kind = str(task.worker_kind or "").strip()
    skill_executor = get_worker_skill_executor(worker_kind)
    if skill_executor is None:
        return None
    return await skill_executor.execute(
        task=task,
        db=db,
        skill_bundle=skill_executor.skill_bundle,
    )


__all__ = ["has_native_review_worker", "run_native_review_worker"]
