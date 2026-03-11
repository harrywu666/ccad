from __future__ import annotations

import importlib
import json
import sys
import time
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
        "routers.feedback",
        "routers.feedback_threads",
        "routers.report",
        "routers.settings",
        "routers.skill_pack",
        "services.feedback_review_queue_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers.") or name.startswith("services.feedback_review"):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("AUDIT_STREAM_HEARTBEAT_SECONDS", "0.01")
    monkeypatch.setenv("AUDIT_STREAM_POLL_SECONDS", "0.01")
    monkeypatch.setenv("AUDIT_STREAM_TEST_ONCE", "1")
    monkeypatch.setenv("FEEDBACK_REVIEW_QUEUE_POLL_SECONDS", "0.01")
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "rule")
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def _seed_project_and_result(session_local, models) -> None:
    db = session_local()
    try:
        db.add(models.Project(id="proj-feedback-stream", name="Feedback Stream Project"))
        db.add(
            models.AuditResult(
                id="audit-result-stream-1",
                project_id="proj-feedback-stream",
                audit_version=2,
                type="index",
                severity="error",
                rule_id="index_alias_rule",
                source_agent="index_review_agent",
                description="索引指向看起来不一致",
            )
        )
        db.commit()
    finally:
        db.close()


def _read_sse_events(response, limit: int = 2):
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


def _wait_for_thread(client: TestClient, thread_id: str, *, expected_statuses: set[str], min_messages: int, timeout_seconds: float = 2.0):
    deadline = time.monotonic() + timeout_seconds
    last_payload = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/projects/proj-feedback-stream/feedback-threads/{thread_id}")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in expected_statuses and len(payload["messages"]) >= min_messages:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"线程状态未在超时前进入目标状态: {last_payload}")


def test_feedback_threads_stream_emits_upsert_event(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/proj-feedback-stream/audit/results/audit-result-stream-1/feedback-thread",
            json={"message": "这是图号别名"},
        )
        thread_id = create_response.json()["id"]

        with client.stream(
            "GET",
            "/api/projects/proj-feedback-stream/feedback-threads/stream",
            params={"audit_version": 2},
        ) as response:
            assert response.status_code == 200
            events = _read_sse_events(response, limit=2)

    assert events[0]["event"] == "feedback_thread_upsert"
    assert thread_id in events[0]["data"]
    assert "result_group_id" in events[0]["data"]
    first_payload = json.loads(events[0]["data"])
    second_payload = json.loads(events[1]["data"])
    assert first_payload["meta"]["thread"]["status"] == "agent_reviewing"
    assert events[1]["event"] == "feedback_thread_upsert"
    assert second_payload["meta"]["thread"]["status"] in {"agent_needs_user_input", "resolved_incorrect", "resolved_not_incorrect"}


def test_feedback_threads_stream_supports_since_id_and_thread_filter(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/proj-feedback-stream/audit/results/audit-result-stream-1/feedback-thread",
            json={"message": "先登记一下"},
        )
        thread_id = create_response.json()["id"]
        _wait_for_thread(
            client,
            thread_id,
            expected_statuses={"agent_needs_user_input"},
            min_messages=2,
        )

        db = session_local()
        try:
            first_event_id = (
                db.query(models.AuditRunEvent)
                .filter(
                    models.AuditRunEvent.project_id == "proj-feedback-stream",
                    models.AuditRunEvent.audit_version == 2,
                    models.AuditRunEvent.event_kind.in_(("feedback_thread_upsert", "feedback_message_created")),
                )
                .order_by(models.AuditRunEvent.id.desc())
                .first()
                .id
            )
        finally:
            db.close()

        client.post(
            f"/api/projects/proj-feedback-stream/feedback-threads/{thread_id}/messages",
            json={"content": "项目里一直叫 A06.01a"},
        )
        _wait_for_thread(
            client,
            thread_id,
            expected_statuses={"resolved_incorrect"},
            min_messages=4,
        )
        with client.stream(
            "GET",
            "/api/projects/proj-feedback-stream/feedback-threads/stream",
            params={"audit_version": 2, "since_id": first_event_id, "thread_id": thread_id},
        ) as response:
            events = _read_sse_events(response, limit=4)

    assert [event["event"] for event in events] == [
        "feedback_message_created",
        "feedback_thread_upsert",
        "feedback_message_created",
        "feedback_thread_upsert",
    ]
    assert all(thread_id in event["data"] for event in events)


def test_feedback_threads_stream_emits_message_created_for_thread_stream(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/proj-feedback-stream/audit/results/audit-result-stream-1/feedback-thread",
            json={"message": "先记一条"},
        )
        thread_id = create_response.json()["id"]
        _wait_for_thread(
            client,
            thread_id,
            expected_statuses={"agent_needs_user_input"},
            min_messages=2,
        )
        db = session_local()
        try:
            since_id = (
                db.query(models.AuditRunEvent)
                .filter(
                    models.AuditRunEvent.project_id == "proj-feedback-stream",
                    models.AuditRunEvent.audit_version == 2,
                    models.AuditRunEvent.event_kind.in_(("feedback_thread_upsert", "feedback_message_created")),
                )
                .order_by(models.AuditRunEvent.id.desc())
                .first()
                .id
            )
        finally:
            db.close()

        client.post(
            f"/api/projects/proj-feedback-stream/feedback-threads/{thread_id}/messages",
            json={"content": "项目里一直叫 A06.01a"},
        )
        _wait_for_thread(
            client,
            thread_id,
            expected_statuses={"resolved_incorrect"},
            min_messages=4,
        )

        with client.stream(
            "GET",
            "/api/projects/proj-feedback-stream/feedback-threads/stream",
            params={"audit_version": 2, "thread_id": thread_id, "since_id": since_id},
        ) as response:
            assert response.status_code == 200
            events = _read_sse_events(response, limit=4)

    first_payload = json.loads(events[0]["data"])
    second_payload = json.loads(events[1]["data"])
    third_payload = json.loads(events[2]["data"])

    assert events[0]["event"] == "feedback_message_created"
    assert first_payload["meta"]["message_item"]["role"] == "user"
    assert events[1]["event"] == "feedback_thread_upsert"
    assert second_payload["meta"]["thread"]["status"] == "agent_reviewing"
    assert events[2]["event"] == "feedback_message_created"
    assert third_payload["meta"]["message_item"]["role"] == "agent"
    assert events[3]["event"] == "feedback_thread_upsert"
