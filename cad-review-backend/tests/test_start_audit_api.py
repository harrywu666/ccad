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
        "services.audit_service",
        "services.audit_runtime_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def _seed_project(session_local, models) -> None:
    db = session_local()
    try:
        db.add(models.Project(id="proj-start-audit", name="Start Audit Project", status="ready"))
        db.commit()
    finally:
        db.close()


def _patch_runtime(monkeypatch) -> None:
    runtime = importlib.import_module("services.audit_runtime_service")
    monkeypatch.setattr(runtime, "mark_stale_running_runs", lambda project_id, db: 0)
    monkeypatch.setattr(runtime, "is_project_running", lambda project_id: False)
    monkeypatch.setattr(runtime, "_set_running", lambda project_id: True)
    monkeypatch.setattr(runtime, "_clear_running", lambda project_id: None)
    monkeypatch.setattr(runtime, "get_next_audit_version", lambda project_id, db: 1)
    monkeypatch.setattr(
        runtime,
        "start_audit_async",
        lambda project_id, audit_version, allow_incomplete=False, provider_mode=None, **kwargs: None,
    )


def test_start_audit_rejects_incomplete_three_line_match_by_default(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _patch_runtime(monkeypatch)

    audit_service = importlib.import_module("services.audit_service")
    monkeypatch.setattr(
        audit_service,
        "match_three_lines",
        lambda project_id, db: {
            "summary": {
                "total": 10,
                "ready": 8,
                "missing_png": 1,
                "missing_json": 1,
                "missing_all": 0,
            },
            "items": [],
        },
    )

    with TestClient(app) as client:
        response = client.post("/api/projects/proj-start-audit/audit/start")

    assert response.status_code == 400
    assert "三线匹配未完成" in response.json()["detail"]


def test_start_audit_allows_incomplete_three_line_match_with_confirmation(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _patch_runtime(monkeypatch)

    audit_service = importlib.import_module("services.audit_service")
    monkeypatch.setattr(
        audit_service,
        "match_three_lines",
        lambda project_id, db: {
            "summary": {
                "total": 10,
                "ready": 8,
                "missing_png": 1,
                "missing_json": 1,
                "missing_all": 0,
            },
            "items": [],
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-start-audit/audit/start",
            json={"allow_incomplete": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["audit_version"] == 1

    db = session_local()
    try:
        run = db.query(models.AuditRun).filter_by(project_id="proj-start-audit", audit_version=1).first()
        project = db.query(models.Project).filter_by(id="proj-start-audit").first()
    finally:
        db.close()

    assert run is not None
    assert run.status == "running"
    assert project is not None
    assert project.status == "auditing"
