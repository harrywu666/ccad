from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_worker_skill_registry_returns_executor_for_index_reference():
    registry = importlib.import_module("services.audit_runtime.worker_skill_registry")

    executor = registry.get_worker_skill_executor("index_reference")

    assert executor is not None
    assert executor.worker_kind == "index_reference"
    assert executor.skill_bundle.worker_kind == "index_reference"


def test_native_review_worker_prefers_registered_skill_executor(monkeypatch):
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    worker_skill_contract = importlib.import_module("services.audit_runtime.worker_skill_contract")
    worker_skill_loader = importlib.import_module("services.audit_runtime.worker_skill_loader")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    async def fake_execute(*, task, db, skill_bundle):  # noqa: ANN001
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.93,
            summary="skill executor ok",
            meta={
                "compat_mode": "native_worker",
                "skill_mode": "worker_skill",
                "skill_id": skill_bundle.worker_kind,
            },
        )

    monkeypatch.setattr(
        review_worker_runtime,
        "get_worker_skill_executor",
        lambda worker_kind: worker_skill_contract.WorkerSkillExecutor(
            worker_kind=worker_kind,
            skill_bundle=worker_skill_loader.load_worker_skill("index_reference"),
            execute=fake_execute,
        ),
    )

    result = asyncio.run(
        review_worker_runtime.run_native_review_worker(
            task=review_task_schema.WorkerTaskCard(
                id="task-skill-registry",
                hypothesis_id="hyp-skill-registry",
                worker_kind="index_reference",
                objective="确认索引引用",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert result is not None
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "index_reference"
