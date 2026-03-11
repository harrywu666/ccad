from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
    monkeypatch.setenv("FEEDBACK_REVIEW_QUEUE_POLL_SECONDS", "0.01")
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "rule")
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def _wait_for_thread(client: TestClient, path: str, *, expected_statuses: set[str], min_messages: int, timeout_seconds: float = 2.0):
    deadline = time.monotonic() + timeout_seconds
    last_payload = None
    while time.monotonic() < deadline:
        response = client.get(path)
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
        db.add(models.Project(id="proj-feedback-thread", name="Feedback Thread Project"))
        db.add(
            models.AuditResult(
                id="audit-result-1",
                project_id="proj-feedback-thread",
                audit_version=2,
                type="index",
                severity="error",
                rule_id="index_alias_rule",
                description="索引指向看起来不一致",
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_grouped_index_results(session_local, models) -> None:
    db = session_local()
    try:
        db.add(models.Project(id="proj-feedback-group", name="Feedback Group Project"))
        db.add_all(
            [
                models.AuditResult(
                    id="issue-1",
                    project_id="proj-feedback-group",
                    audit_version=1,
                    type="index",
                    severity="error",
                    sheet_no_a="A1.01",
                    sheet_no_b="A1.02",
                    location="索引1",
                    rule_id="index_alias_rule",
                    description="图纸A1.01中的索引1指向 A1.02a，但目录/数据中不存在该目标图纸。",
                ),
                models.AuditResult(
                    id="issue-2",
                    project_id="proj-feedback-group",
                    audit_version=1,
                    type="index",
                    severity="error",
                    sheet_no_a="A1.01",
                    sheet_no_b="A1.02",
                    location="索引2",
                    rule_id="index_alias_rule",
                    description="图纸A1.01中的索引2指向 A1.02a，但目录/数据中不存在该目标图纸。",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


def test_open_feedback_thread_creates_initial_user_message(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-1/feedback-thread",
            json={"message": "这条像是图号别名导致的误报"},
        )
        detail_payload = _wait_for_thread(
            client,
            f"/api/projects/proj-feedback-thread/feedback-threads/{response.json()['id']}",
            expected_statuses={"agent_needs_user_input", "resolved_incorrect", "resolved_not_incorrect"},
            min_messages=2,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["audit_result_id"] == "audit-result-1"
    assert payload["status"] == "agent_reviewing"
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["content"] == "这条像是图号别名导致的误报"
    assert detail_payload["messages"][-1]["role"] == "agent"


def test_feedback_thread_detail_and_message_append(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-1/feedback-thread",
            json={"message": "先登记一下"},
        )
        thread_id = create_response.json()["id"]
        initial_detail_payload = _wait_for_thread(
            client,
            f"/api/projects/proj-feedback-thread/feedback-threads/{thread_id}",
            expected_statuses={"agent_needs_user_input"},
            min_messages=2,
        )

        append_response = client.post(
            f"/api/projects/proj-feedback-thread/feedback-threads/{thread_id}/messages",
            json={"content": "这张图在项目里一直叫 A06.01a"},
        )
        detail_payload = _wait_for_thread(
            client,
            f"/api/projects/proj-feedback-thread/feedback-threads/{thread_id}",
            expected_statuses={"resolved_incorrect", "agent_needs_user_input", "resolved_not_incorrect"},
            min_messages=4,
        )
        list_response = client.get(
            f"/api/projects/proj-feedback-thread/feedback-threads/{thread_id}/messages"
        )

    assert append_response.status_code == 200
    append_payload = append_response.json()
    assert append_payload["status"] == "agent_reviewing"
    assert len(append_payload["messages"]) == 3
    assert append_payload["messages"][-1]["role"] == "user"
    assert initial_detail_payload["messages"][-1]["role"] == "agent"
    assert detail_payload["id"] == thread_id
    assert len(detail_payload["messages"]) >= 4
    assert detail_payload["messages"][-2]["content"] == "这张图在项目里一直叫 A06.01a"
    assert detail_payload["messages"][-1]["role"] == "agent"

    assert list_response.status_code == 200
    messages_payload = list_response.json()
    assert len(messages_payload) >= 4
    assert messages_payload[0]["message_type"] == "claim"


def test_get_feedback_thread_by_audit_result(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-1/feedback-thread",
            json={"message": "这是误报"},
        )
        thread_id = create_response.json()["id"]
        response = client.get(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-1/feedback-thread",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == thread_id
    assert payload["audit_result_id"] == "audit-result-1"


def test_list_feedback_threads_by_audit_result_ids(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    db = session_local()
    try:
        db.add(
            models.AuditResult(
                id="audit-result-2",
                project_id="proj-feedback-thread",
                audit_version=2,
                type="dimension",
                severity="warning",
                rule_id="dimension_gap_rule",
                description="尺寸标注疑似误报",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        client.post(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-1/feedback-thread",
            json={"message": "这是图号别名"},
        )
        client.post(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-2/feedback-thread",
            json={"message": "这是项目特例"},
        )
        response = client.get(
            "/api/projects/proj-feedback-thread/feedback-threads",
            params={"audit_result_ids": "audit-result-1,audit-result-2,missing-result"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["audit_result_id"] for item in payload] == ["audit-result-1", "audit-result-2"]

    with TestClient(app) as client:
        query_response = client.post(
            "/api/projects/proj-feedback-thread/feedback-threads/query",
            json={
                "audit_result_ids": ["audit-result-1", "audit-result-2", "missing-result"],
                "audit_version": 2,
            },
        )

    assert query_response.status_code == 200
    query_payload = query_response.json()
    assert [item["audit_result_id"] for item in query_payload] == ["audit-result-1", "audit-result-2"]


def test_grouped_result_reference_creates_and_reads_thread(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_grouped_index_results(session_local, models)

    with TestClient(app) as client:
        grouped_results = client.get(
            "/api/projects/proj-feedback-group/audit/results",
            params={"version": 1, "view": "grouped"},
        ).json()
        group_id = grouped_results[0]["id"]

        create_response = client.post(
            f"/api/projects/proj-feedback-group/audit/results/{group_id}/feedback-thread",
            params={"audit_version": 1},
            json={"message": "这是同一张图的别名"},
        )
        detail_response = client.get(
            f"/api/projects/proj-feedback-group/audit/results/{group_id}/feedback-thread",
            params={"audit_version": 1},
        )
        list_response = client.get(
            "/api/projects/proj-feedback-group/feedback-threads",
            params={"audit_result_ids": group_id, "audit_version": 1},
        )
        query_response = client.post(
            "/api/projects/proj-feedback-group/feedback-threads/query",
            json={"audit_result_ids": [group_id], "audit_version": 1},
        )

    assert create_response.status_code == 200
    create_payload = create_response.json()
    assert create_payload["result_group_id"] == group_id
    assert create_payload["audit_result_id"] in {"issue-1", "issue-2"}

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["result_group_id"] == group_id

    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1
    assert list_payload[0]["result_group_id"] == group_id

    assert query_response.status_code == 200
    query_payload = query_response.json()
    assert len(query_payload) == 1
    assert query_payload[0]["result_group_id"] == group_id


def test_create_feedback_thread_accepts_image_attachments(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-1/feedback-thread",
            data={"message": "我贴了两张图，请一起看"},
            files=[
                ("images", ("proof-1.png", TINY_PNG_BYTES, "image/png")),
                ("images", ("proof-2.png", TINY_PNG_BYTES, "image/png")),
            ],
        )
        detail_payload = _wait_for_thread(
            client,
            f"/api/projects/proj-feedback-thread/feedback-threads/{response.json()['id']}",
            expected_statuses={"agent_needs_user_input", "resolved_incorrect", "resolved_not_incorrect"},
            min_messages=2,
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["messages"]) == 1
    attachments = payload["messages"][0]["attachments"]
    assert len(attachments) == 2
    assert attachments[0]["file_name"] == "proof-1.png"
    assert attachments[0]["mime_type"] == "image/png"
    assert attachments[0]["file_size"] == len(TINY_PNG_BYTES)
    assert attachments[0]["file_url"].endswith("/api/projects/proj-feedback-thread/feedback-attachments/" + attachments[0]["id"] + "/file")
    assert detail_payload["messages"][0]["attachments"][1]["file_name"] == "proof-2.png"


def test_create_feedback_thread_rejects_more_than_three_images(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-1/feedback-thread",
            data={"message": "一口气传四张"},
            files=[
                ("images", ("proof-1.png", TINY_PNG_BYTES, "image/png")),
                ("images", ("proof-2.png", TINY_PNG_BYTES, "image/png")),
                ("images", ("proof-3.png", TINY_PNG_BYTES, "image/png")),
                ("images", ("proof-4.png", TINY_PNG_BYTES, "image/png")),
            ],
        )

    assert response.status_code == 400
    assert "最多只能上传 3 张图片" in response.json()["detail"]


def test_create_feedback_thread_allows_image_only_message(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_result(session_local, models)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-feedback-thread/audit/results/audit-result-1/feedback-thread",
            files=[("images", ("proof-1.png", TINY_PNG_BYTES, "image/png"))],
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["content"] == "（用户上传了图片，请结合图片判断）"
    assert len(payload["messages"][0]["attachments"]) == 1
