from __future__ import annotations

import importlib
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


def _seed_run(database, models, *, project_id: str, audit_version: int, tasks: list[dict]) -> None:
    db = database.SessionLocal()
    try:
        db.add(models.Project(id=project_id, name="Resilience Project", status="auditing"))
        db.add(
            models.AuditRun(
                project_id=project_id,
                audit_version=audit_version,
                status="running",
                current_step="初始化",
                progress=0,
            )
        )
        for task in tasks:
            db.add(
                models.AuditTask(
                    project_id=project_id,
                    audit_version=audit_version,
                    task_type=task["task_type"],
                    source_sheet_no=task.get("source_sheet_no"),
                    target_sheet_no=task.get("target_sheet_no"),
                    priority=task.get("priority", 3),
                )
            )
        db.commit()
    finally:
        db.close()


def _stub_pipeline_prerequisites(monkeypatch, orchestrator, *, planned_tasks: int) -> None:
    monkeypatch.setattr(orchestrator, "match_three_lines", lambda *args, **kwargs: {"summary": {"total": 1, "ready": 1, "missing_png": 0, "missing_json": 0, "missing_all": 0}})
    monkeypatch.setattr(orchestrator, "build_sheet_contexts", lambda *args, **kwargs: {"ready": 1})
    monkeypatch.setattr(orchestrator, "_run_relationship_runner", lambda *args, **kwargs: [])
    monkeypatch.setattr(orchestrator, "save_ai_edges", lambda *args, **kwargs: 0)
    monkeypatch.setattr(orchestrator, "build_audit_tasks", lambda *args, **kwargs: {"total_tasks": planned_tasks})
    monkeypatch.setattr(orchestrator, "increment_cache_version", lambda *args, **kwargs: None)


def _fetch_run_and_tasks(database, models, *, project_id: str, audit_version: int):
    db = database.SessionLocal()
    try:
        run = (
            db.query(models.AuditRun)
            .filter(
                models.AuditRun.project_id == project_id,
                models.AuditRun.audit_version == audit_version,
            )
            .first()
        )
        tasks = (
            db.query(models.AuditTask)
            .filter(
                models.AuditTask.project_id == project_id,
                models.AuditTask.audit_version == audit_version,
            )
            .all()
        )
        task_status = {
            (task.task_type, task.source_sheet_no, task.target_sheet_no): task.status
            for task in tasks
        }
        return run, task_status
    finally:
        db.close()


def test_execute_pipeline_keeps_running_when_index_agent_stage_fails(monkeypatch, tmp_path):
    database, models, orchestrator = _load_modules(monkeypatch, tmp_path)
    _seed_run(
        database,
        models,
        project_id="proj-orchestrator-index",
        audit_version=1,
        tasks=[
            {"task_type": "index", "source_sheet_no": "A1.01"},
            {"task_type": "dimension", "source_sheet_no": "A1.01", "target_sheet_no": "A1.02"},
            {"task_type": "material", "source_sheet_no": "M1.01"},
        ],
    )
    _stub_pipeline_prerequisites(monkeypatch, orchestrator, planned_tasks=3)
    monkeypatch.setattr(orchestrator, "audit_indexes", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("index boom")))
    monkeypatch.setattr(orchestrator, "audit_dimensions", lambda *args, **kwargs: [{"id": "dim-1"}])
    monkeypatch.setattr(orchestrator, "audit_materials", lambda *args, **kwargs: [{"id": "mat-1"}])

    orchestrator.execute_pipeline_legacy(
        "proj-orchestrator-index",
        1,
        allow_incomplete=False,
        clear_running=lambda *_: None,
    )

    run, task_status = _fetch_run_and_tasks(
        database,
        models,
        project_id="proj-orchestrator-index",
        audit_version=1,
    )
    assert run is not None
    assert run.status == "done"
    assert run.total_issues == 2
    assert task_status[("index", "A1.01", None)] == "failed"
    assert task_status[("dimension", "A1.01", "A1.02")] == "done"
    assert task_status[("material", "M1.01", None)] == "done"


def test_execute_pipeline_continues_to_material_after_dimension_stage_fails(monkeypatch, tmp_path):
    database, models, orchestrator = _load_modules(monkeypatch, tmp_path)
    _seed_run(
        database,
        models,
        project_id="proj-orchestrator-dimension",
        audit_version=1,
        tasks=[
            {"task_type": "index", "source_sheet_no": "A1.01"},
            {"task_type": "dimension", "source_sheet_no": "A1.01", "target_sheet_no": "A1.02"},
            {"task_type": "material", "source_sheet_no": "M1.01"},
        ],
    )
    _stub_pipeline_prerequisites(monkeypatch, orchestrator, planned_tasks=3)
    monkeypatch.setattr(orchestrator, "audit_indexes", lambda *args, **kwargs: [])
    monkeypatch.setattr(orchestrator, "audit_dimensions", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("dimension boom")))
    monkeypatch.setattr(orchestrator, "audit_materials", lambda *args, **kwargs: [{"id": "mat-1"}])

    orchestrator.execute_pipeline_legacy(
        "proj-orchestrator-dimension",
        1,
        allow_incomplete=False,
        clear_running=lambda *_: None,
    )

    run, task_status = _fetch_run_and_tasks(
        database,
        models,
        project_id="proj-orchestrator-dimension",
        audit_version=1,
    )
    assert run is not None
    assert run.status == "done"
    assert run.total_issues == 1
    assert task_status[("index", "A1.01", None)] == "done"
    assert task_status[("dimension", "A1.01", "A1.02")] == "failed"
    assert task_status[("material", "M1.01", None)] == "done"
