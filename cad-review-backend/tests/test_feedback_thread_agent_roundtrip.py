from __future__ import annotations

import importlib
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
        "routers.feedback_threads",
        "services.feedback_agent_service",
        "services.feedback_agent_types",
        "services.feedback_review_queue_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers.") or name.startswith("services.feedback_agent") or name.startswith("services.feedback_review"):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("FEEDBACK_REVIEW_QUEUE_POLL_SECONDS", "0.01")
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "rule")
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def _wait_for_thread(client: TestClient, thread_id: str, *, expected_statuses: set[str], min_messages: int, timeout_seconds: float = 2.0):
    deadline = time.monotonic() + timeout_seconds
    last_payload = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/projects/proj-thread-agent/feedback-threads/{thread_id}")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload
        if payload["status"] in expected_statuses and len(payload["messages"]) >= min_messages:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"线程状态未在超时前进入目标状态: {last_payload}")


def _seed_project_and_result(session_local, models) -> None:
    db = session_local()
    try:
        db.add(models.Project(id="proj-thread-agent", name="Thread Agent Project"))
        db.add(
            models.AuditResult(
                id="audit-result-agent",
                project_id="proj-thread-agent",
                audit_version=2,
                type="index",
                severity="error",
                rule_id="index_alias_rule",
                confidence=0.52,
                description="索引指向疑似不一致",
            )
        )
        db.commit()
    finally:
        db.close()


def test_feedback_thread_generates_agent_reply_on_open(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-thread-agent/audit/results/audit-result-agent/feedback-thread",
            json={"message": "这是误报"},
        )
        detail_payload = _wait_for_thread(
            client,
            response.json()["id"],
            expected_statuses={"agent_needs_user_input"},
            min_messages=2,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "agent_reviewing"
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"
    assert detail_payload["status"] == "agent_needs_user_input"
    assert len(detail_payload["messages"]) == 2
    assert detail_payload["messages"][1]["role"] == "agent"


def test_feedback_thread_appends_agent_reply_after_user_follow_up(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/proj-thread-agent/audit/results/audit-result-agent/feedback-thread",
            json={"message": "这是误报"},
        )
        thread_id = create_response.json()["id"]
        initial_detail_payload = _wait_for_thread(
            client,
            thread_id,
            expected_statuses={"agent_needs_user_input"},
            min_messages=2,
        )

        response = client.post(
            f"/api/projects/proj-thread-agent/feedback-threads/{thread_id}/messages",
            json={"content": "这张图在项目里一直叫 A06.01a"},
        )
        detail_payload = _wait_for_thread(
            client,
            thread_id,
            expected_statuses={"resolved_incorrect"},
            min_messages=4,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "agent_reviewing"
    assert len(payload["messages"]) == 3
    assert payload["messages"][-1]["role"] == "user"
    assert initial_detail_payload["messages"][-1]["role"] == "agent"
    assert detail_payload["status"] == "resolved_incorrect"
    assert len(detail_payload["messages"]) == 4
    assert detail_payload["messages"][-1]["role"] == "agent"
    assert "误判" in detail_payload["messages"][-1]["content"] or "误报" in detail_payload["messages"][-1]["content"]


def test_feedback_thread_rejects_append_while_reviewing(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/proj-thread-agent/audit/results/audit-result-agent/feedback-thread",
            json={"message": "这是误报"},
        )
        thread_id = create_response.json()["id"]
        response = client.post(
            f"/api/projects/proj-thread-agent/feedback-threads/{thread_id}/messages",
            json={"content": "补充一句"},
        )

    assert response.status_code == 409
    assert "还在处理中" in response.json()["detail"]


def test_feedback_thread_marks_unavailable_when_sdk_is_disconnected(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    feedback_threads = importlib.import_module("routers.feedback_threads")

    def _broken_decide_feedback_thread(**kwargs):  # noqa: ANN001
        raise RuntimeError("kimi sdk unavailable")

    monkeypatch.setattr(feedback_threads, "decide_feedback_thread", _broken_decide_feedback_thread)
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "llm")
    monkeypatch.setenv("FEEDBACK_AGENT_PROVIDER", "sdk")

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-thread-agent/audit/results/audit-result-agent/feedback-thread",
            json={"message": "这是误报"},
        )
        detail_payload = _wait_for_thread(
            client,
            response.json()["id"],
            expected_statuses={"agent_unavailable"},
            min_messages=2,
        )

    assert response.status_code == 200
    assert detail_payload["status"] == "agent_unavailable"
    assert detail_payload["messages"][-1]["role"] == "system"
    assert "当前未联通" in detail_payload["messages"][-1]["content"]
