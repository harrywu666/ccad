from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime
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
    monkeypatch.setenv("AUDIT_STREAM_HEARTBEAT_SECONDS", "0.01")
    monkeypatch.setenv("AUDIT_STREAM_POLL_SECONDS", "0.01")
    monkeypatch.setenv("AUDIT_STREAM_TEST_ONCE", "1")
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def _read_sse_events(response, limit: int = 3):
    events = []
    current: dict[str, str] = {}
    for line in response.iter_lines():
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if line == "":
            if current:
                events.append(current)
                current = {}
                if len(events) >= limit:
                    break
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key] = value.lstrip()
    return events


def test_audit_results_stream_filters_non_result_events(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-results-stream", name="Results Stream"))
        db.add(models.AuditRun(project_id="proj-results-stream", audit_version=2, status="running"))
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-results-stream",
                    audit_version=2,
                    level="info",
                    step_key="task_planning",
                    agent_key="master_planner_agent",
                    agent_name="总控规划Agent",
                    event_kind="phase_event",
                    progress_hint=18,
                    message="这个是过程日志，不该进入结果流",
                    created_at=datetime.now(),
                ),
                models.AuditRunEvent(
                    project_id="proj-results-stream",
                    audit_version=2,
                    level="info",
                    step_key="result_stream",
                    agent_key="runner_agent",
                    agent_name="Runner Agent",
                    event_kind="result_upsert",
                    message="Runner Agent 已向报告追加一条问题",
                    meta_json=json.dumps(
                        {
                            "delta_kind": "upsert",
                            "view": "grouped",
                            "row": {"id": "group_1", "type": "index", "issue_ids": ["i1"]},
                            "counts": {"total": 1, "unresolved": {"index": 1, "dimension": 0, "material": 0}},
                        },
                        ensure_ascii=False,
                    ),
                    created_at=datetime.now(),
                ),
                models.AuditRunEvent(
                    project_id="proj-results-stream",
                    audit_version=2,
                    level="info",
                    step_key="result_stream",
                    agent_key="runner_agent",
                    agent_name="Runner Agent",
                    event_kind="result_summary",
                    message="Runner Agent 已同步报告汇总：当前共 1 条问题",
                    meta_json=json.dumps(
                        {"delta_kind": "summary", "view": "grouped", "counts": {"total": 1}},
                        ensure_ascii=False,
                    ),
                    created_at=datetime.now(),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/projects/proj-results-stream/audit/results/stream",
            params={"version": 2},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            events = _read_sse_events(response)

    assert events[0]["event"] == "result_upsert"
    assert events[0].get("id")
    assert "group_1" in events[0]["data"]
    assert events[1]["event"] == "result_summary"
    assert events[2]["event"] == "heartbeat"


def test_audit_results_stream_supports_since_id(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-results-since", name="Results Since"))
        db.add(models.AuditRun(project_id="proj-results-since", audit_version=1, status="running"))
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-results-since",
                    audit_version=1,
                    level="info",
                    step_key="result_stream",
                    agent_key="runner_agent",
                    agent_name="Runner Agent",
                    event_kind="result_upsert",
                    message="旧问题",
                    meta_json=json.dumps({"delta_kind": "upsert", "row": {"id": "group_old"}}, ensure_ascii=False),
                    created_at=datetime.now(),
                ),
                models.AuditRunEvent(
                    project_id="proj-results-since",
                    audit_version=1,
                    level="info",
                    step_key="result_stream",
                    agent_key="runner_agent",
                    agent_name="Runner Agent",
                    event_kind="result_upsert",
                    message="新问题",
                    meta_json=json.dumps({"delta_kind": "upsert", "row": {"id": "group_new"}}, ensure_ascii=False),
                    created_at=datetime.now(),
                ),
            ]
        )
        db.commit()
        since_id = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-results-since",
                models.AuditRunEvent.message == "旧问题",
            )
            .first()
            .id
        )
    finally:
        db.close()

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/projects/proj-results-since/audit/results/stream",
            params={"version": 1, "since_id": since_id},
        ) as response:
            events = _read_sse_events(response, limit=1)

    assert len(events) == 1
    assert events[0]["event"] == "result_upsert"
    assert "group_new" in events[0]["data"]

