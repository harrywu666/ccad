from __future__ import annotations

import importlib
import sys
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
        "services.audit_runtime.state_transitions",
        "services.audit_runtime.agent_reports",
    )
    for name in list(sys.modules):
        if (
            name in targets
            or name.startswith("routers.")
            or name.startswith("services.audit_runtime")
        ):
            sys.modules.pop(name, None)


def _load_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    state_transitions = importlib.import_module("services.audit_runtime.state_transitions")
    reports = importlib.import_module("services.audit_runtime.agent_reports")
    database.init_db()
    return main.app, database.SessionLocal, models, state_transitions, reports


def test_dimension_agent_internal_reports_do_not_become_final_results(monkeypatch, tmp_path):
    app, session_local, models, state_transitions, reports = _load_runtime(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-dim-final", name="Dimension Final"))
        db.add(
            models.AuditRun(
                project_id="proj-dim-final",
                audit_version=1,
                status="running",
                current_step="尺寸核对（27任务）",
                progress=45,
                total_issues=0,
            )
        )
        db.commit()
    finally:
        db.close()

    state_transitions.append_agent_status_report(
        "proj-dim-final",
        1,
        step_key="dimension",
        agent_key="dimension_review_agent",
        agent_name="尺寸审查Agent",
        progress_hint=60,
        report=reports.DimensionAgentReport(
            batch_summary="第 4 批尺寸关系结果不稳",
            blocking_issues=[{"kind": "unstable_output"}],
            runner_help_request="restart_subsession",
            agent_confidence=0.28,
            next_recommended_action="rerun_current_batch",
        ),
    )

    with TestClient(app) as client:
        status_response = client.get("/api/projects/proj-dim-final/audit/status")
        results_response = client.get(
            "/api/projects/proj-dim-final/audit/results",
            params={"version": 1},
        )
        events_response = client.get(
            "/api/projects/proj-dim-final/audit/events",
            params={"version": 1},
        )

    assert status_response.status_code == 200
    assert status_response.json()["total_issues"] == 0

    assert results_response.status_code == 200
    assert results_response.json() == []

    assert events_response.status_code == 200
    payload = events_response.json()["items"]
    internal_event = next(item for item in payload if item["event_kind"] == "agent_status_reported")
    broadcast_event = next(item for item in payload if item["event_kind"] == "runner_broadcast")
    assert internal_event["meta"]["report_scope"] == "internal_only"
    assert broadcast_event["meta"]["report_scope"] == "progress_only"
