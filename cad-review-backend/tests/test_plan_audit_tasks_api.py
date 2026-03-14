from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "main",
        "routers.audit",
        "routers.projects",
        "routers.categories",
        "routers.catalog",
        "routers.drawings",
        "routers.dwg",
        "routers.report",
        "routers.settings",
        "routers.feedback",
        "routers.skill_pack",
        "services.context_service",
        "services.task_planner_service",
        "services.master_planner_service",
        "services.audit_runtime_service",
        "services.audit_runtime.orchestrator",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("AUDIT_MASTER_PLANNER_ENABLED", "0")
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def test_plan_audit_tasks_returns_review_kernel_runtime_summary(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-plan-api", name="Plan API Project"))
        db.add_all(
            [
                models.SheetContext(
                    id="ctx-a101",
                    project_id="proj-plan-api",
                    sheet_no="A1.01",
                    sheet_name="平面布置图",
                    status="ready",
                    meta_json='{"stats":{"indexes":1}}',
                ),
                models.SheetContext(
                    id="ctx-a401",
                    project_id="proj-plan-api",
                    sheet_no="A4.01",
                    sheet_name="节点详图",
                    status="ready",
                    meta_json='{"stats":{"indexes":0}}',
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.post("/api/projects/proj-plan-api/audit/tasks/plan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["relationship_summary"]["discovered"] == 0
    assert payload["relationship_summary"]["source"] == "review_kernel_runtime"
    assert payload["task_summary"]["index_tasks"] == 0
    assert payload["task_summary"]["dimension_tasks"] == 0
    assert payload["task_summary"]["material_tasks"] == 0


def test_plan_audit_tasks_uses_v2_relationship_runner_when_flag_enabled(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-plan-api-v2", name="Plan API V2 Project"))
        db.add(
            models.SheetContext(
                id="ctx-a101-v2",
                project_id="proj-plan-api-v2",
                sheet_no="A1.01",
                sheet_name="平面布置图",
                status="ready",
                meta_json='{"stats":{"indexes":1}}',
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.post("/api/projects/proj-plan-api-v2/audit/tasks/plan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["context_summary"]["mode"] == "review_kernel_v1"
    assert payload["relationship_summary"]["source"] == "review_kernel_runtime"
