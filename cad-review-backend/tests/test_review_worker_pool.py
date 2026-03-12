from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_review_worker_pool_runs_tasks_in_parallel():
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")
    review_worker_pool = importlib.import_module("services.audit_runtime.review_worker_pool")

    active = 0
    peak = 0

    async def _fake_worker(task):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.9,
            summary=f"{task.id} ok",
        )

    pool = review_worker_pool.ReviewWorkerPool(
        max_concurrency=4,
        worker_runner=_fake_worker,
    )
    tasks = [
        review_task_schema.WorkerTaskCard(
            id=f"task-{index}",
            hypothesis_id="hyp-1",
            worker_kind="elevation_consistency",
            objective=f"check-{index}",
            source_sheet_no="A3-01",
            target_sheet_nos=["A2-01"],
        )
        for index in range(3)
    ]

    results = asyncio.run(pool.run_batch(tasks))

    assert len(results) == 3
    assert peak >= 2


def test_worker_pool_uses_assignment_id_as_visible_session_key():
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")
    review_worker_pool = importlib.import_module("services.audit_runtime.review_worker_pool")

    async def _fake_worker(task):
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.9,
            summary=f"{task.id} ok",
            meta={"session_key": task.session_key},
        )

    pool = review_worker_pool.ReviewWorkerPool(
        max_concurrency=1,
        worker_runner=_fake_worker,
    )
    task = review_task_schema.WorkerTaskCard(
        id="asg-1",
        hypothesis_id="hyp-1",
        worker_kind="elevation_consistency",
        objective="check-1",
        source_sheet_no="A3-01",
        target_sheet_nos=["A2-01"],
        context={"assignment_id": "asg-1"},
    )

    results = asyncio.run(pool.run_batch([task]))

    assert results[0].meta["assignment_id"] == "asg-1"
    assert results[0].meta["visible_session_key"] == "assignment:asg-1"
