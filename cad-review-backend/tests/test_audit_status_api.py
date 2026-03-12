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


def test_audit_status_infers_planning_state_from_recent_events_without_run(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-status-planning", name="Planning Status"))
        db.add(
            models.AuditRunEvent(
                project_id="proj-status-planning",
                audit_version=7,
                level="info",
                step_key="relationship_discovery",
                agent_key="relationship_review_agent",
                agent_name="关系审查Agent",
                event_kind="runner_broadcast",
                progress_hint=14,
                message="关系审查Agent 正在整理值得继续复核的候选关系",
                meta_json=json.dumps(
                    {
                        "provider_name": "sdk",
                        "pipeline_mode": "chief_review",
                        "planner_source": "chief_agent",
                        "task_stage": "worker_relationship_discovery",
                        "prompt_source": "agent_skill",
                        "skill_id": "node_host_binding",
                        "skill_mode": "worker_skill",
                        "session_key": "worker_skill:node_host_binding:A101:A401",
                        "evidence_selection_policy": "source_target_linked_pair",
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-status-planning/audit/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "auditing"
    assert payload["run_status"] == "planning"
    assert payload["audit_version"] == 7
    assert payload["current_step"] == "节点归属 Skill 整理候选关系"
    assert payload["progress"] == 14
    assert payload["provider_mode"] == "sdk"
    assert payload["pipeline_mode"] == "chief_review"
    assert payload["planner_source"] == "chief_agent"
    assert payload["task_stage"] == "worker_relationship_discovery"
    assert payload["prompt_source"] == "agent_skill"
    assert payload["skill_id"] == "node_host_binding"
    assert payload["skill_mode"] == "worker_skill"
    assert payload["session_key"] == "worker_skill:node_host_binding:A101:A401"
    assert payload["evidence_selection_policy"] == "source_target_linked_pair"


def test_audit_status_uses_first_event_time_as_total_started_at(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    planning_started_at = datetime.now() - timedelta(minutes=4, seconds=30)
    run_started_at = planning_started_at + timedelta(minutes=2)

    db = session_local()
    try:
        db.add(models.Project(id="proj-status-total-time", name="Total Time Status", status="auditing"))
        db.add(
            models.AuditRunEvent(
                project_id="proj-status-total-time",
                audit_version=3,
                level="info",
                step_key="relationship_discovery",
                agent_key="relationship_review_agent",
                agent_name="关系审查Agent",
                event_kind="runner_broadcast",
                progress_hint=14,
                message="关系审查Agent 正在分析跨图关系",
                created_at=planning_started_at,
            )
        )
        db.add(
            models.AuditRun(
                project_id="proj-status-total-time",
                audit_version=3,
                status="running",
                current_step="尺寸核对",
                progress=52,
                total_issues=0,
                provider_mode="kimi_sdk",
                started_at=run_started_at,
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-status-total-time/audit/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_status"] == "running"
    assert payload["started_at"] == planning_started_at.isoformat()
    assert payload["pipeline_mode"] == "chief_review"
    assert payload["planner_source"] == "chief_agent"


def test_audit_status_prefers_latest_worker_stage_title_over_old_run_step(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-status-stage-title", name="Stage Title Status", status="auditing"))
        db.add(
            models.AuditRun(
                project_id="proj-status-stage-title",
                audit_version=5,
                status="running",
                current_step="尺寸核对",
                progress=52,
                total_issues=0,
                provider_mode="api",
                started_at=datetime.now() - timedelta(minutes=3),
            )
        )
        db.add(
            models.AuditRunEvent(
                project_id="proj-status-stage-title",
                audit_version=5,
                level="info",
                step_key="dimension",
                agent_key="dimension_review_agent",
                agent_name="尺寸审查Agent",
                event_kind="runner_broadcast",
                progress_hint=62,
                message="尺寸审查Agent 正在继续推进当前审图步骤",
                meta_json=json.dumps(
                    {
                        "pipeline_mode": "chief_review",
                        "planner_source": "chief_agent",
                        "task_stage": "worker_pair_compare",
                        "prompt_source": "agent_skill",
                        "skill_id": "elevation_consistency",
                        "skill_mode": "worker_skill",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-status-stage-title/audit/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_step"] == "标高一致性 Skill 执行双图对比"
    assert payload["task_stage"] == "worker_pair_compare"
    assert payload["skill_id"] == "elevation_consistency"
