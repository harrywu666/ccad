from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    """清除已加载的后端模块，确保测试使用隔离的数据库。"""
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
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    """加载测试应用并将数据库隔离到临时 HOME 目录。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def _seed_project(session_local, models) -> None:
    """创建测试项目。"""
    db = session_local()
    try:
        project = models.Project(id="proj-feedback", name="Feedback Project")
        db.add(project)
        db.commit()
    finally:
        db.close()


def _seed_grouped_index_results(session_local, models) -> None:
    """创建两条会被 grouped 视图合并的索引问题。"""
    db = session_local()
    try:
        db.add_all(
            [
                models.AuditResult(
                    id="issue-1",
                    project_id="proj-feedback",
                    audit_version=1,
                    type="index",
                    severity="error",
                    sheet_no_a="A1.01",
                    sheet_no_b="A1.02",
                    location="索引1",
                    description="图纸A1.01中的索引1指向 A1.02a，但目录/数据中不存在该目标图纸。",
                ),
                models.AuditResult(
                    id="issue-2",
                    project_id="proj-feedback",
                    audit_version=1,
                    type="index",
                    severity="error",
                    sheet_no_a="A1.01",
                    sheet_no_b="A1.02",
                    location="索引2",
                    description="图纸A1.01中的索引2指向 A1.02a，但目录/数据中不存在该目标图纸。",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


def test_get_grouped_audit_results_includes_feedback_fields(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_grouped_index_results(session_local, models)

    with TestClient(app) as client:
        response = client.get(
            "/api/projects/proj-feedback/audit/results",
            params={"version": 1, "view": "grouped"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["issue_ids"] == ["issue-1", "issue-2"]
    assert payload[0]["feedback_status"] == "none"
    assert payload[0]["feedback_at"] is None


def test_batch_update_audit_results_marks_grouped_items_as_incorrect(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_grouped_index_results(session_local, models)

    with TestClient(app) as client:
        patch_response = client.patch(
            "/api/projects/proj-feedback/audit/results/batch",
            json={
                "result_ids": ["issue-1", "issue-2"],
                "feedback_status": "incorrect",
            },
        )
        results_response = client.get(
            "/api/projects/proj-feedback/audit/results",
            params={"version": 1, "view": "raw"},
        )

    assert patch_response.status_code == 200
    assert patch_response.json()["success"] is True

    raw_items = results_response.json()
    assert len(raw_items) == 2
    assert {item["feedback_status"] for item in raw_items} == {"incorrect"}
    assert all(item["feedback_at"] is not None for item in raw_items)


def test_update_audit_result_can_clear_feedback_status(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_grouped_index_results(session_local, models)

    with TestClient(app) as client:
        client.patch(
            "/api/projects/proj-feedback/audit/results/issue-1",
            json={"feedback_status": "incorrect"},
        )
        clear_response = client.patch(
            "/api/projects/proj-feedback/audit/results/issue-1",
            json={"feedback_status": "none"},
        )

    assert clear_response.status_code == 200
    payload = clear_response.json()
    assert payload["id"] == "issue-1"
    assert payload["feedback_status"] == "none"
    assert payload["feedback_at"] is None
