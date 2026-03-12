from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_native_review_worker_returns_native_card_before_wrapper(monkeypatch):
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
            summary="native skill executor ok",
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
                id="task-native-first",
                hypothesis_id="hyp-native-first",
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
    assert result.meta["compat_mode"] == "native_worker"
    assert result.meta["skill_mode"] == "worker_skill"


def test_wrapper_path_is_only_used_when_skill_executor_missing(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    review_worker_runtime = importlib.import_module("services.audit_runtime.review_worker_runtime")
    dimension_audit = importlib.import_module("services.audit.dimension_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _FakeSession:
        def close(self):
            return None

    called = {"wrapper": False}

    async def fake_native_runner(*, task, db):  # noqa: ANN001
        del task, db
        return None

    def fake_dimension_wrapper(project_id, audit_version, db, task):  # noqa: ANN001
        del project_id, audit_version, db
        called["wrapper"] = True
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.81,
            summary="legacy wrapper fallback",
            meta={
                "compat_mode": "worker_wrapper",
                "legacy_fallback": True,
                "fallback_origin": "legacy_dimension_wrapper",
            },
        )

    monkeypatch.setattr(orchestrator, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(review_worker_runtime, "run_native_review_worker", fake_native_runner)
    monkeypatch.setattr(dimension_audit, "run_dimension_worker_wrapper", fake_dimension_wrapper)

    result = asyncio.run(
        orchestrator._default_chief_worker_runner(
            review_task_schema.WorkerTaskCard(
                id="task-wrapper-fallback",
                hypothesis_id="hyp-wrapper-fallback",
                worker_kind="spatial_consistency",
                objective="核对 A1.01 与 A4.01",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-bridge", "audit_version": 11},
            )
        )
    )

    assert called["wrapper"] is True
    assert result.meta["compat_mode"] == "worker_wrapper"
    assert result.meta["legacy_fallback"] is True
