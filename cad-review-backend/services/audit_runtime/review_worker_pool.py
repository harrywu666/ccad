"""副审任务并发执行池。"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from services.audit_runtime.review_task_schema import WorkerResultCard, WorkerTaskCard


WorkerRunner = Callable[[WorkerTaskCard], Awaitable[WorkerResultCard]]


async def _default_worker_runner(task: WorkerTaskCard) -> WorkerResultCard:
    raise NotImplementedError(f"worker runner is not configured for task {task.id}")


class ReviewWorkerPool:
    def __init__(
        self,
        *,
        max_concurrency: int = 4,
        worker_runner: WorkerRunner | None = None,
    ) -> None:
        self.max_concurrency = max(1, int(max_concurrency or 1))
        self._worker_runner = worker_runner or _default_worker_runner

    async def run_batch(self, tasks: list[WorkerTaskCard]) -> list[WorkerResultCard]:
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _run(task: WorkerTaskCard) -> WorkerResultCard:
            async with semaphore:
                return await self._worker_runner(task)

        return await asyncio.gather(*[_run(task) for task in tasks])


__all__ = ["ReviewWorkerPool"]
