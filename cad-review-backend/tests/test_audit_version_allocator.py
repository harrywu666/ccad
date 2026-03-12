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
        "services.audit_runtime_service",
    )
    for name in list(sys.modules):
        if name in targets:
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    runtime = importlib.import_module("services.audit_runtime_service")
    database.init_db()
    return database, models, runtime


def test_get_next_audit_version_uses_memory_events_and_tasks(monkeypatch, tmp_path):
    database, models, runtime = _load_modules(monkeypatch, tmp_path)
    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-version", name="Version Project", status="ready"))
        db.add(models.AuditRun(project_id="proj-version", audit_version=2, status="done"))
        db.add(models.AuditResult(project_id="proj-version", audit_version=3))
        db.add(
            models.ProjectMemoryRecord(
                project_id="proj-version",
                audit_version=7,
                memory_json='{"active_hypotheses":[]}',
            )
        )
        db.add(
            models.AuditRunEvent(
                project_id="proj-version",
                audit_version=6,
                message="chief review finished",
            )
        )
        db.add(
            models.AuditTask(
                project_id="proj-version",
                audit_version=5,
                task_type="index",
                status="done",
            )
        )
        db.commit()

        next_version = runtime.get_next_audit_version("proj-version", db)
    finally:
        db.close()

    assert next_version == 8
