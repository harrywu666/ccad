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


def test_audit_events_stream_replays_history_and_emits_heartbeat(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-stream-events", name="Stream Events"))
        db.add(models.AuditRun(project_id="proj-stream-events", audit_version=2, status="running"))
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-stream-events",
                    audit_version=2,
                    level="info",
                    step_key="task_planning",
                    agent_key="master_planner_agent",
                    agent_name="总控规划Agent",
                    event_kind="model_stream_delta",
                    progress_hint=18,
                    message="正在整理图纸上下文",
                    meta_json=json.dumps({"source": "master_planner_stream"}, ensure_ascii=False),
                    created_at=datetime.now(),
                ),
                models.AuditRunEvent(
                    project_id="proj-stream-events",
                    audit_version=2,
                    level="info",
                    step_key="task_planning",
                    agent_key="master_planner_agent",
                    agent_name="总控规划Agent",
                    event_kind="phase_event",
                    progress_hint=18,
                    message="总控规划Agent 正在等待 Kimi 继续输出",
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
            "/api/projects/proj-stream-events/audit/events/stream",
            params={"version": 2},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            events = _read_sse_events(response)

    assert events[0]["event"] == "model_stream_delta"
    assert "正在整理图纸上下文" in events[0]["data"]
    assert events[1]["event"] == "phase_event"
    assert "总控规划Agent 正在等待 Kimi 继续输出" in events[1]["data"]
    assert events[2]["event"] == "heartbeat"


def test_audit_events_stream_supports_since_id(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-stream-since", name="Stream Since"))
        db.add(models.AuditRun(project_id="proj-stream-since", audit_version=1, status="running"))
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-stream-since",
                    audit_version=1,
                    level="info",
                    step_key="task_planning",
                    agent_key="master_planner_agent",
                    agent_name="总控规划Agent",
                    event_kind="phase_event",
                    progress_hint=18,
                    message="旧事件",
                    created_at=datetime.now(),
                ),
                models.AuditRunEvent(
                    project_id="proj-stream-since",
                    audit_version=1,
                    level="info",
                    step_key="task_planning",
                    agent_key="master_planner_agent",
                    agent_name="总控规划Agent",
                    event_kind="model_stream_delta",
                    progress_hint=18,
                    message="新事件",
                    created_at=datetime.now(),
                ),
            ]
        )
        db.commit()
        since_id = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-stream-since",
                models.AuditRunEvent.message == "旧事件",
            )
            .first()
            .id
        )
    finally:
        db.close()

    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/projects/proj-stream-since/audit/events/stream",
            params={"version": 1, "since_id": since_id},
        ) as response:
            events = _read_sse_events(response, limit=1)

    assert len(events) == 1
    assert events[0]["event"] == "model_stream_delta"
    assert "新事件" in events[0]["data"]
