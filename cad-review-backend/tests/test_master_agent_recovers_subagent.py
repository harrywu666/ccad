from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.audit_runtime.orchestrator",
        "services.audit_runtime.state_transitions",
        "services.audit_runtime.task_recovery_memory",
        "services.audit_runtime.master_agent_recovery",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime"):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    database.init_db()
    models = importlib.import_module("models")
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    return database, models, orchestrator


def _seed_run(database, models, *, project_id: str, audit_version: int) -> None:
    db = database.SessionLocal()
    try:
        db.add(models.Project(id=project_id, name="Recovery Project", status="auditing"))
        db.add(
            models.AuditRun(
                project_id=project_id,
                audit_version=audit_version,
                status="running",
                current_step="初始化",
                progress=0,
            )
        )
        db.add(
            models.AuditTask(
                id="task-dim-1",
                project_id=project_id,
                audit_version=audit_version,
                task_type="dimension",
                source_sheet_no="A1.01",
                target_sheet_no="A1.02",
                status="pending",
                trace_json=json.dumps({"planner": "task_planner_v1"}, ensure_ascii=False),
            )
        )
        db.commit()
    finally:
        db.close()


def _stub_pipeline_prerequisites(monkeypatch, orchestrator):
    monkeypatch.setattr(orchestrator, "match_three_lines", lambda *args, **kwargs: {"summary": {"total": 1, "ready": 1, "missing_png": 0, "missing_json": 0, "missing_all": 0}})
    monkeypatch.setattr(orchestrator, "build_sheet_contexts", lambda *args, **kwargs: {"ready": 1})
    monkeypatch.setattr(orchestrator, "_run_relationship_runner", lambda *args, **kwargs: [])
    monkeypatch.setattr(orchestrator, "save_ai_edges", lambda *args, **kwargs: 0)
    monkeypatch.setattr(orchestrator, "build_audit_tasks", lambda *args, **kwargs: {"total_tasks": 1})
    monkeypatch.setattr(orchestrator, "increment_cache_version", lambda *args, **kwargs: None)
    monkeypatch.setattr(orchestrator, "audit_indexes", lambda *args, **kwargs: [])
    monkeypatch.setattr(orchestrator, "audit_materials", lambda *args, **kwargs: [])


def test_master_agent_retries_failed_dimension_stage_with_task_memory(monkeypatch, tmp_path):
    database, models, orchestrator = _load_modules(monkeypatch, tmp_path)
    _seed_run(database, models, project_id="proj-master-recover", audit_version=1)
    _stub_pipeline_prerequisites(monkeypatch, orchestrator)

    attempts = {"count": 0}

    def _fake_audit_dimensions(project_id, audit_version, db, pair_filters, hot_sheet_registry=None):  # noqa: ANN001
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("dimension stage boom")
        return [{"id": "dim-ok"}]

    monkeypatch.setattr(orchestrator, "audit_dimensions", _fake_audit_dimensions)

    orchestrator.execute_pipeline_legacy(
        "proj-master-recover",
        1,
        allow_incomplete=False,
        clear_running=lambda *_: None,
    )

    db = database.SessionLocal()
    try:
        run = (
            db.query(models.AuditRun)
            .filter(
                models.AuditRun.project_id == "proj-master-recover",
                models.AuditRun.audit_version == 1,
            )
            .first()
        )
        task = db.query(models.AuditTask).filter(models.AuditTask.id == "task-dim-1").first()
        events = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-master-recover",
                models.AuditRunEvent.audit_version == 1,
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    assert attempts["count"] == 2
    assert run is not None
    assert run.status == "done"
    assert task is not None
    assert task.status == "done"
    trace = json.loads(task.trace_json or "{}")
    runtime_entries = trace.get("runtime") or []
    recovery_entries = [entry for entry in runtime_entries if entry.get("event") == "master_recovery_attempted"]
    assert recovery_entries
    assert recovery_entries[-1]["restart_count"] == 1
    event_kinds = [row.event_kind for row in events]
    assert "master_recovery_requested" in event_kinds
    assert "master_recovery_succeeded" in event_kinds


def test_master_agent_marks_task_permanently_failed_after_restart_budget_is_exhausted(monkeypatch, tmp_path):
    database, models, orchestrator = _load_modules(monkeypatch, tmp_path)
    _seed_run(database, models, project_id="proj-master-exhausted", audit_version=1)
    _stub_pipeline_prerequisites(monkeypatch, orchestrator)

    attempts = {"count": 0}

    def _always_fail_dimensions(*args, **kwargs):  # noqa: ANN001
        attempts["count"] += 1
        raise RuntimeError("dimension keeps failing")

    monkeypatch.setattr(orchestrator, "audit_dimensions", _always_fail_dimensions)

    orchestrator.execute_pipeline_legacy(
        "proj-master-exhausted",
        1,
        allow_incomplete=False,
        clear_running=lambda *_: None,
    )

    db = database.SessionLocal()
    try:
        run = (
            db.query(models.AuditRun)
            .filter(
                models.AuditRun.project_id == "proj-master-exhausted",
                models.AuditRun.audit_version == 1,
            )
            .first()
        )
        task = db.query(models.AuditTask).filter(models.AuditTask.id == "task-dim-1").first()
        events = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-master-exhausted",
                models.AuditRunEvent.audit_version == 1,
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    assert attempts["count"] == 4
    assert run is not None
    assert run.status == "done"
    assert task is not None
    assert task.status == "failed"
    assert task.result_ref == "permanently_failed"
    trace = json.loads(task.trace_json or "{}")
    runtime_entries = trace.get("runtime") or []
    assert any(entry.get("event") == "master_recovery_exhausted" for entry in runtime_entries)
    event_kinds = [row.event_kind for row in events]
    assert "master_recovery_exhausted" in event_kinds
