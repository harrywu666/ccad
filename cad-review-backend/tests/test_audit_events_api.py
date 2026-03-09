from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta
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


def test_get_audit_events_filters_by_version_and_returns_plain_fields(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-events", name="Events Project"))
        db.add_all(
            [
                models.AuditRun(project_id="proj-events", audit_version=2, status="running"),
                models.AuditRun(project_id="proj-events", audit_version=3, status="running"),
            ]
        )
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-events",
                    audit_version=2,
                    level="info",
                    step_key="prepare",
                    message="旧版本日志",
                    meta_json=json.dumps({"group": 0}, ensure_ascii=False),
                    created_at=datetime.now() - timedelta(minutes=2),
                ),
                models.AuditRunEvent(
                    project_id="proj-events",
                    audit_version=3,
                    level="info",
                    step_key="relationship_discovery",
                    message="正在处理第 1 组图纸，共 3 组",
                    meta_json=json.dumps({"group_index": 1}, ensure_ascii=False),
                    created_at=datetime.now() - timedelta(minutes=1),
                ),
                models.AuditRunEvent(
                    project_id="proj-events",
                    audit_version=3,
                    level="success",
                    step_key="relationship_discovery",
                    message="第 1 组图纸关系分析完成，发现 2 处关联",
                    meta_json=json.dumps({"group_index": 1, "found": 2}, ensure_ascii=False),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-events/audit/events", params={"version": 3})

    assert response.status_code == 200
    payload = response.json()
    assert [item["message"] for item in payload["items"]] == [
        "正在处理第 1 组图纸，共 3 组",
        "第 1 组图纸关系分析完成，发现 2 处关联",
    ]
    assert payload["items"][0]["audit_version"] == 3
    assert payload["items"][0]["meta"] == {"group_index": 1}
    assert payload["items"][0]["level"] == "info"
    assert payload["items"][1]["level"] == "success"


def test_get_audit_events_supports_since_id_incremental_polling(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-events-incremental", name="Events Incremental"))
        db.add(models.AuditRun(project_id="proj-events-incremental", audit_version=1, status="running"))
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-events-incremental",
                    audit_version=1,
                    level="info",
                    step_key="prepare",
                    message="开始准备审图数据",
                ),
                models.AuditRunEvent(
                    project_id="proj-events-incremental",
                    audit_version=1,
                    level="success",
                    step_key="prepare",
                    message="图纸信息整理完成，共 12 张图纸可进入审图",
                ),
                models.AuditRunEvent(
                    project_id="proj-events-incremental",
                    audit_version=1,
                    level="warning",
                    step_key="relationship_discovery",
                    message="第 2 组图纸分析时间较长，系统仍在继续",
                ),
            ]
        )
        db.commit()
        second_event_id = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-events-incremental",
                models.AuditRunEvent.message == "图纸信息整理完成，共 12 张图纸可进入审图",
            )
            .first()
            .id
        )
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get(
            "/api/projects/proj-events-incremental/audit/events",
            params={"version": 1, "since_id": second_event_id},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["message"] for item in payload["items"]] == [
        "第 2 组图纸分析时间较长，系统仍在继续",
    ]
    assert payload["next_since_id"] == payload["items"][-1]["id"]
