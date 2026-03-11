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
        "services.audit_runtime.task_recovery_memory",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime.task_recovery_memory"):
            sys.modules.pop(name, None)


def _load_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()
    memory_module = importlib.import_module("services.audit_runtime.task_recovery_memory")
    return database, models, memory_module


def test_task_recovery_memory_builds_from_task_batch_and_existing_trace(monkeypatch, tmp_path):
    database, models, memory_module = _load_runtime(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-task-memory", name="Task Memory"))
        db.add(
            models.AuditTask(
                id="task-dim-1",
                project_id="proj-task-memory",
                audit_version=1,
                task_type="dimension",
                source_sheet_no="A1.01",
                target_sheet_no="A1.02",
                status="running",
                trace_json=json.dumps(
                    {
                        "planner": "task_planner_v1",
                        "runtime": [
                            {"event": "master_recovery_attempted", "restart_count": 1},
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        task = db.query(models.AuditTask).filter(models.AuditTask.id == "task-dim-1").first()
    finally:
        db.close()

    assert task is not None
    memory = memory_module.build_task_recovery_memory(
        [task],
        task_type="dimension",
        current_batch_key="dimension:A1.01->A1.02",
        last_error="dimension worker boom",
        last_help_request="restart_subsession",
        partial_outputs=[{"id": "dim-partial"}],
    )

    assert memory.task_type == "dimension"
    assert memory.task_ids == ["task-dim-1"]
    assert memory.source_sheet_nos == ["A1.01"]
    assert memory.target_sheet_nos == ["A1.02"]
    assert memory.restart_count == 1
    assert memory.last_help_request == "restart_subsession"
    assert memory.partial_outputs == [{"id": "dim-partial"}]

