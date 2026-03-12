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


def test_audit_status_includes_ui_runtime_snapshot(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    now = datetime.now()

    db = session_local()
    try:
        db.add(models.Project(id="proj-status-ui-runtime", name="UI Runtime Status", status="auditing"))
        db.add(
            models.AuditRun(
                project_id="proj-status-ui-runtime",
                audit_version=9,
                status="running",
                current_step="主审派发副审任务",
                progress=41,
                total_issues=4,
                provider_mode="sdk",
                started_at=now - timedelta(minutes=8),
            )
        )
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-status-ui-runtime",
                    audit_version=9,
                    level="success",
                    step_key="chief_prompt",
                    agent_key="chief_review_agent",
                    agent_name="主审 Agent",
                    event_kind="phase_completed",
                    progress_hint=12,
                    message="主审 Agent 已装配本轮审图资源，生成 18 条待核对怀疑卡",
                    created_at=now - timedelta(minutes=6),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-ui-runtime",
                    audit_version=9,
                    level="success",
                    step_key="task_planning",
                    agent_key="chief_review_agent",
                    agent_name="主审 Agent",
                    event_kind="phase_completed",
                    progress_hint=18,
                    message="主审 Agent 已生成 10 张副审任务卡",
                    created_at=now - timedelta(minutes=5, seconds=30),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-ui-runtime",
                    audit_version=9,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_turn_started",
                    progress_hint=35,
                    message="尺寸审查Agent 已通过 Runner 发起一次流式调用",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "turn_kind": "dimension_sheet_semantic",
                            "session_key": "proj-status-ui-runtime:9:dimension_review_agent:sheet_semantic:A101",
                            "skill_id": "elevation_consistency",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=4),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-ui-runtime",
                    audit_version=9,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="provider_stream_delta",
                    progress_hint=36,
                    message='{"raw":"ignored"}',
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "turn_kind": "dimension_sheet_semantic",
                            "session_key": "proj-status-ui-runtime:9:dimension_review_agent:sheet_semantic:A101",
                            "skill_id": "elevation_consistency",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=3, seconds=50),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-ui-runtime",
                    audit_version=9,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_broadcast",
                    progress_hint=37,
                    message="尺寸审查Agent 正在抽取 A101 的单图标高语义",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "turn_kind": "dimension_sheet_semantic",
                            "session_key": "proj-status-ui-runtime:9:dimension_review_agent:sheet_semantic:A101",
                            "skill_id": "elevation_consistency",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=3, seconds=45),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-ui-runtime",
                    audit_version=9,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_turn_started",
                    progress_hint=38,
                    message="尺寸审查Agent 已通过 Runner 发起一次流式调用",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "turn_kind": "dimension_sheet_semantic",
                            "session_key": "proj-status-ui-runtime:9:dimension_review_agent:sheet_semantic:A101",
                            "skill_id": "elevation_consistency",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=3, seconds=44),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-ui-runtime",
                    audit_version=9,
                    level="success",
                    step_key="index",
                    agent_key="index_review_agent",
                    agent_name="索引审查Agent",
                    event_kind="raw_output_saved",
                    progress_hint=39,
                    message="索引审查Agent 的原始输出已保存，便于后续排查",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "turn_kind": "dimension_pair_compare",
                            "session_key": "proj-status-ui-runtime:9:index_review_agent:pair_compare:A201:A401",
                            "skill_id": "index_reference",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=2),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-ui-runtime",
                    audit_version=9,
                    level="warning",
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    event_kind="runner_turn_deferred",
                    progress_hint=40,
                    message="关系审查Agent 这一步暂时还没拿到稳定结果，Runner 先记下并继续处理后续步骤",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "turn_kind": "relationship_candidate_review",
                            "session_key": "proj-status-ui-runtime:9:relationship_review_agent:candidate_review:7a2185fd3cdc",
                            "skill_id": "node_host_binding",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-status-ui-runtime/audit/status")

    assert response.status_code == 200
    payload = response.json()
    ui_runtime = payload["ui_runtime"]
    assert ui_runtime["chief"]["title"] == "主审"
    assert ui_runtime["chief"]["assigned_task_count"] == 10
    assert ui_runtime["chief"]["active_worker_count"] == 1
    assert ui_runtime["chief"]["completed_worker_count"] == 1
    assert ui_runtime["chief"]["blocked_worker_count"] == 1
    assert ui_runtime["chief"]["queued_task_count"] == 7
    assert ui_runtime["chief"]["issue_count"] == 4

    worker_sessions = ui_runtime["worker_sessions"]
    assert len(worker_sessions) == 2
    first_active = next(item for item in worker_sessions if item["status"] == "active")
    assert first_active["session_key"] == "proj-status-ui-runtime:9:dimension_review_agent:sheet_semantic:A101"
    assert first_active["worker_name"] == "标高副审"
    assert first_active["skill_label"] == "标高一致性 Skill"
    assert first_active["task_title"] == "图纸 A101"
    assert first_active["current_action"] == "正在抽取单图标高语义"
    assert len(first_active["recent_actions"]) == 2
    assert all(action["text"] != '{"raw":"ignored"}' for action in first_active["recent_actions"])

    blocked = next(item for item in worker_sessions if item["status"] == "blocked")
    assert blocked["task_title"] == "候选关系 7a2185fd"
    assert blocked["current_action"] == "等待重试或主审介入"

    recent_completed = ui_runtime["recent_completed"]
    assert len(recent_completed) == 1
    assert recent_completed[0]["session_key"] == "proj-status-ui-runtime:9:index_review_agent:pair_compare:A201:A401"
    assert recent_completed[0]["status"] == "completed"
    assert recent_completed[0]["task_title"] == "A201 ↔ A401"


def test_status_api_reports_one_worker_card_per_assignment_even_when_multiple_internal_runner_events_exist(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    now = datetime.now()

    db = session_local()
    try:
        db.add(models.Project(id="proj-status-assignment-collapsed", name="Assignment Collapse", status="auditing"))
        db.add(
            models.AuditRun(
                project_id="proj-status-assignment-collapsed",
                audit_version=11,
                status="running",
                current_step="主审派发副审任务",
                progress=52,
                total_issues=0,
                provider_mode="sdk",
                started_at=now - timedelta(minutes=8),
            )
        )
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-status-assignment-collapsed",
                    audit_version=11,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_turn_started",
                    progress_hint=20,
                    message="尺寸审查Agent 已通过 Runner 发起一次流式调用",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "assignment_id": "asg-1",
                            "visible_session_key": "assignment:asg-1",
                            "turn_kind": "dimension_sheet_semantic",
                            "session_key": "proj-status-assignment-collapsed:11:dimension_review_agent:sheet_semantic:A101",
                            "skill_id": "elevation_consistency",
                            "source_sheet_no": "A1.01",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=3),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-assignment-collapsed",
                    audit_version=11,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_broadcast",
                    progress_hint=21,
                    message="尺寸审查Agent 正在抽取 A101 的单图标高语义",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "assignment_id": "asg-1",
                            "visible_session_key": "assignment:asg-1",
                            "turn_kind": "dimension_sheet_semantic",
                            "session_key": "proj-status-assignment-collapsed:11:dimension_review_agent:sheet_semantic:A101",
                            "skill_id": "elevation_consistency",
                            "source_sheet_no": "A1.01",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=2, seconds=50),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-assignment-collapsed",
                    audit_version=11,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_broadcast",
                    progress_hint=22,
                    message="尺寸审查Agent 正在比对 A101 与 A201",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "assignment_id": "asg-1",
                            "visible_session_key": "assignment:asg-1",
                            "turn_kind": "dimension_pair_compare",
                            "session_key": "proj-status-assignment-collapsed:11:dimension_review_agent:pair_compare:A101:A201",
                            "skill_id": "elevation_consistency",
                            "source_sheet_no": "A1.01",
                            "target_sheet_no": "A2.01",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=2, seconds=40),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-status-assignment-collapsed/audit/status")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["ui_runtime"]["worker_sessions"]) == 1
    assert payload["ui_runtime"]["worker_sessions"][0]["session_key"] == "assignment:asg-1"


def test_status_api_does_not_reinflate_worker_cards_when_assignment_and_legacy_events_mix(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    now = datetime.now()

    db = session_local()
    try:
        db.add(models.Project(id="proj-status-assignment-mixed", name="Assignment Mixed", status="auditing"))
        db.add(
            models.AuditRun(
                project_id="proj-status-assignment-mixed",
                audit_version=12,
                status="running",
                current_step="主审派发副审任务",
                progress=53,
                total_issues=0,
                provider_mode="sdk",
                started_at=now - timedelta(minutes=8),
            )
        )
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-status-assignment-mixed",
                    audit_version=12,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_broadcast",
                    progress_hint=21,
                    message="尺寸审查Agent 正在抽取 A101 的单图标高语义",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "assignment_id": "asg-1",
                            "visible_session_key": "assignment:asg-1",
                            "turn_kind": "dimension_sheet_semantic",
                            "session_key": "proj-status-assignment-mixed:12:dimension_review_agent:sheet_semantic:A101",
                            "skill_id": "elevation_consistency",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=2, seconds=50),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-assignment-mixed",
                    audit_version=12,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_broadcast",
                    progress_hint=22,
                    message="尺寸审查Agent 正在比对 A101 与 A201",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "turn_kind": "dimension_pair_compare",
                            "session_key": "proj-status-assignment-mixed:12:dimension_review_agent:pair_compare:A101:A201",
                            "skill_id": "elevation_consistency",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=2, seconds=40),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-assignment-mixed",
                    audit_version=12,
                    level="warning",
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    event_kind="runner_turn_deferred",
                    progress_hint=23,
                    message="关系审查Agent 这一步暂时还没拿到稳定结果",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "assignment_id": "asg-2",
                            "visible_session_key": "assignment:asg-2",
                            "turn_kind": "relationship_candidate_review",
                            "session_key": "proj-status-assignment-mixed:12:relationship_review_agent:candidate_review:7a2185fd3cdc",
                            "skill_id": "node_host_binding",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-status-assignment-mixed/audit/status")

    assert response.status_code == 200
    payload = response.json()
    worker_sessions = payload["ui_runtime"]["worker_sessions"]
    assert len(worker_sessions) <= 2
    assert {item["session_key"] for item in worker_sessions} == {
        "assignment:asg-1",
        "assignment:asg-2",
    }


def test_status_api_moves_completed_assignment_into_recent_completed(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    now = datetime.now()

    db = session_local()
    try:
        db.add(models.Project(id="proj-status-assignment-completed", name="Assignment Completed", status="auditing"))
        db.add(
            models.AuditRun(
                project_id="proj-status-assignment-completed",
                audit_version=13,
                status="running",
                current_step="主审派发副审任务",
                progress=53,
                total_issues=0,
                provider_mode="sdk",
                started_at=now - timedelta(minutes=8),
            )
        )
        db.add_all(
            [
                models.AuditRunEvent(
                    project_id="proj-status-assignment-completed",
                    audit_version=13,
                    level="info",
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    event_kind="runner_turn_started",
                    progress_hint=20,
                    message="尺寸审查Agent 已通过 Runner 发起一次流式调用",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "assignment_id": "asg-1",
                            "visible_session_key": "assignment:asg-1",
                            "session_key": "proj-status-assignment-completed:13:dimension_review_agent:pair_compare:A101:A201",
                            "skill_id": "elevation_consistency",
                            "source_sheet_no": "A1.01",
                            "target_sheet_no": "A2.01",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=2),
                ),
                models.AuditRunEvent(
                    project_id="proj-status-assignment-completed",
                    audit_version=13,
                    level="success",
                    step_key="dimension",
                    agent_key="elevation_consistency_agent",
                    agent_name="副审 Agent",
                    event_kind="worker_assignment_completed",
                    progress_hint=60,
                    message="A1.01 与 A2.01 标高一致，无需继续升级",
                    meta_json=json.dumps(
                        {
                            "actor_role": "worker",
                            "assignment_id": "asg-1",
                            "visible_session_key": "assignment:asg-1",
                            "session_key": "proj-status-assignment-completed:13:dimension_review_agent:pair_compare:A101:A201",
                            "skill_id": "elevation_consistency",
                            "worker_kind": "elevation_consistency",
                            "worker_result_status": "rejected",
                            "source_sheet_no": "A1.01",
                            "target_sheet_no": "A2.01",
                            "task_stage": "worker_skill_execution",
                        },
                        ensure_ascii=False,
                    ),
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-status-assignment-completed/audit/status")

    assert response.status_code == 200
    payload = response.json()
    ui_runtime = payload["ui_runtime"]
    assert ui_runtime["chief"]["active_worker_count"] == 0
    assert ui_runtime["chief"]["completed_worker_count"] == 1
    assert ui_runtime["worker_sessions"] == []
    assert len(ui_runtime["recent_completed"]) == 1
    assert ui_runtime["recent_completed"][0]["session_key"] == "assignment:asg-1"
    assert ui_runtime["recent_completed"][0]["status"] == "completed"
