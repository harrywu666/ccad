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
        db.add(models.Project(id="proj-provider-select", name="Provider Select Project", status="ready"))
        db.commit()
    finally:
        db.close()


def _patch_runtime(monkeypatch) -> list[str | None]:
    runtime = importlib.import_module("services.audit_runtime_service")
    seen_provider_modes: list[str | None] = []
    monkeypatch.setattr(runtime, "mark_stale_running_runs", lambda project_id, db: 0)
    monkeypatch.setattr(runtime, "is_project_running", lambda project_id: False)
    monkeypatch.setattr(runtime, "_set_running", lambda project_id: True)
    monkeypatch.setattr(runtime, "_clear_running", lambda project_id: None)
    monkeypatch.setattr(runtime, "get_next_audit_version", lambda project_id, db: 1)

    def _fake_start_audit_async(project_id, audit_version, allow_incomplete=False, provider_mode=None):  # noqa: ANN001
        seen_provider_modes.append(provider_mode)

    monkeypatch.setattr(runtime, "start_audit_async", _fake_start_audit_async)
    return seen_provider_modes


def test_audit_run_normalizes_removed_codex_provider_to_kimi_sdk(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    seen_provider_modes = _patch_runtime(monkeypatch)

    audit_service = importlib.import_module("services.audit_service")
    monkeypatch.setattr(
        audit_service,
        "match_three_lines",
        lambda project_id, db: {
            "summary": {
                "total": 1,
                "ready": 1,
                "missing_png": 0,
                "missing_json": 0,
                "missing_all": 0,
            },
            "items": [],
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-provider-select/audit/start",
            json={"provider_mode": "codex_sdk"},
        )

    assert response.status_code == 200

    db = session_local()
    try:
        run = db.query(models.AuditRun).filter_by(project_id="proj-provider-select", audit_version=1).first()
    finally:
        db.close()

    assert run is not None
    assert run.provider_mode == "kimi_sdk"
    assert seen_provider_modes == ["kimi_sdk"]
