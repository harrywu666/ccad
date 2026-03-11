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
        "services.audit_runtime.runner_broadcasts",
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


def test_relationship_agent_report_is_written_as_internal_event_and_runner_broadcast(monkeypatch, tmp_path):
    session_local, models, state_transitions, reports = _load_runtime(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-rel-report-bridge", name="Relationship Report Bridge"))
        db.add(models.AuditRun(project_id="proj-rel-report-bridge", audit_version=1, status="running"))
        db.commit()
    finally:
        db.close()

    state_transitions.append_agent_status_report(
        "proj-rel-report-bridge",
        1,
        step_key="relationship_discovery",
        agent_key="relationship_review_agent",
        agent_name="关系审查Agent",
        progress_hint=15,
        report=reports.RelationshipAgentReport(
            batch_summary="第 1 批候选关系复核结果不稳",
            blocking_issues=[{"kind": "unstable_output", "stage": "candidate_review"}],
            runner_help_request="restart_subsession",
            agent_confidence=0.33,
            next_recommended_action="rerun_current_batch",
        ),
    )

    db = session_local()
    try:
        rows = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-rel-report-bridge",
                models.AuditRunEvent.audit_version == 1,
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    internal_row = next(row for row in rows if row.event_kind == "agent_status_reported")
    internal_meta = json.loads(internal_row.meta_json or "{}")
    assert internal_meta["runner_help_request"] == "restart_subsession"
    assert internal_meta["stream_layer"] == "internal_agent_report"

    broadcast_row = next(row for row in rows if row.event_kind == "runner_broadcast")
    assert "关系审查Agent" in broadcast_row.message
    assert "不稳" in broadcast_row.message
