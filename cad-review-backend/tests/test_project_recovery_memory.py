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
        "services.audit_runtime.project_recovery_memory",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime.project_recovery_memory"):
            sys.modules.pop(name, None)


def _load_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()
    memory_module = importlib.import_module("services.audit_runtime.project_recovery_memory")
    return database, models, memory_module


def test_project_recovery_memory_summarizes_task_and_event_state(monkeypatch, tmp_path):
    database, models, memory_module = _load_runtime(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-project-memory", name="Project Recovery"))
        db.add(
            models.AuditRun(
                project_id="proj-project-memory",
                audit_version=2,
                status="running",
                current_step="尺寸核对（4任务）",
                progress=52,
            )
        )
        db.add_all(
            [
                models.AuditTask(project_id="proj-project-memory", audit_version=2, task_type="index", source_sheet_no="A1.01", status="done"),
                models.AuditTask(project_id="proj-project-memory", audit_version=2, task_type="dimension", source_sheet_no="A1.01", target_sheet_no="A1.02", status="running"),
                models.AuditTask(project_id="proj-project-memory", audit_version=2, task_type="material", source_sheet_no="M1.01", status="failed"),
            ]
        )
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-project-memory",
                    audit_version=2,
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="agent_status_reported",
                    message="第 3 批尺寸关系结果不稳",
                ),
                models.AuditRunEvent(
                    project_id="proj-project-memory",
                    audit_version=2,
                    agent_key="master_planner_agent",
                    agent_name="总控规划Agent",
                    event_kind="master_recovery_requested",
                    message="总控规划Agent 正在带着这批任务的记忆重启 尺寸审查Agent",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    memory = memory_module.load_project_recovery_memory("proj-project-memory", audit_version=2)

    assert memory.project_id == "proj-project-memory"
    assert memory.audit_version == 2
    assert memory.current_stage == "尺寸核对（4任务）"
    assert memory.task_summary["done"] == 1
    assert memory.task_summary["running"] == 1
    assert memory.task_summary["failed"] == 1
    assert memory.recent_agent_reports[0]["agent_key"] == "dimension_review_agent"
    assert memory.recent_master_actions[0]["event_kind"] == "master_recovery_requested"

