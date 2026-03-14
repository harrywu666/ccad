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
        "services.audit_runtime.result_view",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime"):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    state_transitions = importlib.import_module("services.audit_runtime.state_transitions")
    database.init_db()
    return database.SessionLocal, models, state_transitions


def test_append_result_upsert_events_emits_grouped_delta(monkeypatch, tmp_path):
    session_local, models, state_transitions = _load_modules(monkeypatch, tmp_path)
    issue_a_id = ""
    issue_b_id = ""
    db = session_local()
    try:
        db.add(models.Project(id="proj-bridge", name="Bridge"))
        db.add(models.AuditRun(project_id="proj-bridge", audit_version=1, status="running"))
        issue_a = models.AuditResult(
            project_id="proj-bridge",
            audit_version=1,
            type="index",
            severity="warning",
            sheet_no_a="G0.03",
            sheet_no_b="G0.04b",
            location="索引A1",
            description="图纸G0.03中的索引A1 指向 G0.04b，但目录/数据中不存在该目标图。",
            evidence_json=json.dumps({"anchors": []}, ensure_ascii=False),
        )
        issue_b = models.AuditResult(
            project_id="proj-bridge",
            audit_version=1,
            type="index",
            severity="warning",
            sheet_no_a="G0.03",
            sheet_no_b="G0.04b",
            location="索引A2",
            description="图纸G0.03中的索引A2 指向 G0.04b，但目录/数据中不存在该目标图。",
            evidence_json=json.dumps({"anchors": []}, ensure_ascii=False),
        )
        db.add(issue_a)
        db.add(issue_b)
        db.commit()
        issue_a_id = issue_a.id
        issue_b_id = issue_b.id
    finally:
        db.close()

    state_transitions.append_result_upsert_events(
        "proj-bridge",
        1,
        issue_ids=[issue_a_id, issue_b_id],
    )

    db = session_local()
    try:
        events = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-bridge",
                models.AuditRunEvent.audit_version == 1,
                models.AuditRunEvent.event_kind == "result_upsert",
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    assert len(events) == 1
    payload = json.loads(events[0].meta_json or "{}")
    assert payload["delta_kind"] == "upsert"
    assert payload["view"] == "grouped"
    assert payload["row"]["id"].startswith("group_")
    assert sorted(payload["row"]["issue_ids"]) == sorted([issue_a_id, issue_b_id])
    assert sorted(item["id"] for item in payload["raw_rows"]) == sorted([issue_a_id, issue_b_id])
    assert payload["counts"]["total"] == 1
    assert payload["counts"]["unresolved"]["index"] == 1


def test_append_result_summary_event_emits_counts(monkeypatch, tmp_path):
    session_local, models, state_transitions = _load_modules(monkeypatch, tmp_path)
    db = session_local()
    try:
        db.add(models.Project(id="proj-summary", name="Summary"))
        db.add(models.AuditRun(project_id="proj-summary", audit_version=3, status="running"))
        db.add(
            models.AuditResult(
                project_id="proj-summary",
                audit_version=3,
                type="dimension",
                severity="warning",
                sheet_no_a="A1.00",
                sheet_no_b="A1.00a",
                location="下部横向",
                description="尺寸不一致",
                evidence_json=json.dumps({"anchors": []}, ensure_ascii=False),
            )
        )
        db.commit()
    finally:
        db.close()

    state_transitions.append_result_summary_event("proj-summary", 3)

    db = session_local()
    try:
        event = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-summary",
                models.AuditRunEvent.audit_version == 3,
                models.AuditRunEvent.event_kind == "result_summary",
            )
            .first()
        )
    finally:
        db.close()

    assert event is not None
    payload = json.loads(event.meta_json or "{}")
    assert payload["delta_kind"] == "summary"
    assert payload["counts"]["total"] == 1
    assert payload["counts"]["unresolved"]["dimension"] == 1
