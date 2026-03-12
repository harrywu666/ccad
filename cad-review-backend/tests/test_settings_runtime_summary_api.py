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
        "routers.settings",
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


def test_get_audit_runtime_summaries_only_returns_finished_runs_with_internal_summary(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add_all(
            [
                models.Project(id="proj-runtime-1", name="test1"),
                models.Project(id="proj-runtime-2", name="test2"),
            ]
        )
        db.add_all(
            [
                models.AuditRun(
                    project_id="proj-runtime-1",
                    audit_version=3,
                    status="done",
                    current_step="生成报告",
                    provider_mode="kimi_sdk",
                    started_at=datetime.now() - timedelta(minutes=7),
                    finished_at=datetime.now() - timedelta(minutes=1),
                ),
                models.AuditRun(
                    project_id="proj-runtime-2",
                    audit_version=1,
                    status="running",
                    current_step="关系复核",
                    provider_mode="kimi_sdk",
                    started_at=datetime.now() - timedelta(minutes=2),
                ),
            ]
        )
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-runtime-1",
                    audit_version=3,
                    level="warning",
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    event_kind="output_validation_failed",
                    progress_hint=15,
                    message="关系审查Agent 的输出结构不完整",
                    meta_json=json.dumps({"actor_role": "worker"}, ensure_ascii=False),
                ),
                models.AuditRunEvent(
                    project_id="proj-runtime-1",
                    audit_version=3,
                    level="info",
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    event_kind="agent_status_reported",
                    progress_hint=15,
                    message="第 2 批候选关系复核结果不稳",
                    meta_json=json.dumps(
                        {
                            "runner_help_request": "restart_subsession",
                            "stream_layer": "internal_agent_report",
                            "actor_role": "worker",
                        },
                        ensure_ascii=False,
                    ),
                ),
                models.AuditRunEvent(
                    project_id="proj-runtime-1",
                    audit_version=3,
                    level="info",
                    step_key="relationship_discovery",
                    agent_key="runner_observer_agent",
                    agent_name="Runner观察Agent",
                    event_kind="runner_help_requested",
                    progress_hint=15,
                    message="Runner 已收到关系审查Agent 的求助请求",
                    meta_json=json.dumps({"source_agent_key": "relationship_review_agent"}, ensure_ascii=False),
                ),
                models.AuditRunEvent(
                    project_id="proj-runtime-1",
                    audit_version=3,
                    level="info",
                    step_key="relationship_discovery",
                    agent_key="runner_observer_agent",
                    agent_name="Runner观察Agent",
                    event_kind="runner_help_resolved",
                    progress_hint=15,
                    message="Runner 已处理关系审查Agent 的求助请求",
                    meta_json=json.dumps({"source_agent_key": "relationship_review_agent"}, ensure_ascii=False),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/settings/audit-runtime-summaries")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["project_id"] == "proj-runtime-1"
    assert item["project_name"] == "test1"
    assert item["counts"]["agent_status_reported"] == 1
    assert item["counts"]["runner_help_requested"] == 1
    assert item["counts"]["runner_help_resolved"] == 1
    assert item["counts"]["output_validation_failed"] == 1
    assert item["counts"]["worker_events"] >= 2
    assert item["agent_summaries"][0]["agent_key"] == "relationship_review_agent"
    assert item["agent_summaries"][0]["agent_role"] == "worker"
    assert item["agent_summaries"][0]["help_requested_count"] == 1
    assert item["recent_notes"][-1]["agent_role"] == "observer"
    assert item["recent_notes"][-1]["message"] == "Runner 已处理关系审查Agent 的求助请求"
