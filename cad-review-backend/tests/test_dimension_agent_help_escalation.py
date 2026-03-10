from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.audit_runtime.state_transitions",
        "services.audit_runtime.agent_reports",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime"):
            sys.modules.pop(name, None)


def _load_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    state_transitions = importlib.import_module("services.audit_runtime.state_transitions")
    reports = importlib.import_module("services.audit_runtime.agent_reports")
    database.init_db()
    return database.SessionLocal, models, state_transitions, reports


def test_runner_executes_dimension_agent_help_request_without_ending_run(monkeypatch, tmp_path):
    session_local, models, state_transitions, reports = _load_runtime(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-dim-help", name="Dimension Help"))
        db.add(
            models.AuditRun(
                project_id="proj-dim-help",
                audit_version=1,
                status="running",
                current_step="尺寸核对（27任务）",
                progress=45,
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        state_transitions,
        "_restart_runner_subsession",
        lambda project_id, audit_version, *, agent_key: True,
    )

    state_transitions.append_agent_status_report(
        "proj-dim-help",
        1,
        step_key="dimension",
        agent_key="dimension_review_agent",
        agent_name="尺寸审查Agent",
        progress_hint=60,
        report=reports.DimensionAgentReport(
            batch_summary="第 3 批尺寸关系结果不稳",
            blocking_issues=[{"kind": "unstable_output"}],
            runner_help_request="restart_subsession",
            agent_confidence=0.31,
            next_recommended_action="rerun_current_batch",
        ),
    )

    db = session_local()
    try:
        run = (
            db.query(models.AuditRun)
            .filter(
                models.AuditRun.project_id == "proj-dim-help",
                models.AuditRun.audit_version == 1,
            )
            .first()
        )
        rows = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-dim-help",
                models.AuditRunEvent.audit_version == 1,
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    assert run is not None
    assert run.status == "running"
    event_kinds = [row.event_kind for row in rows]
    assert "runner_help_requested" in event_kinds
    assert "runner_help_resolved" in event_kinds

    resolved_row = next(row for row in rows if row.event_kind == "runner_help_resolved")
    payload = json.loads(resolved_row.meta_json or "{}")
    assert payload["action_name"] == "restart_subsession"
    assert payload["executed"] is True
