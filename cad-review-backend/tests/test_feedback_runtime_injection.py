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
        "services.feedback_runtime_service",
        "services.task_planner_service",
        "services.audit_runtime.evidence_planner",
        "services.audit.relationship_discovery",
        "services.audit.material_audit",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime") or name.startswith("services.audit.relationship_discovery"):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    feedback_runtime_service = importlib.import_module("services.feedback_runtime_service")
    task_planner_service = importlib.import_module("services.task_planner_service")
    evidence_planner = importlib.import_module("services.audit_runtime.evidence_planner")
    relationship_discovery = importlib.import_module("services.audit.relationship_discovery")
    material_audit = importlib.import_module("services.audit.material_audit")
    database.init_db()
    return database, models, feedback_runtime_service, task_planner_service, evidence_planner, relationship_discovery, material_audit


def test_feedback_runtime_profile_influences_planning_and_evidence(monkeypatch, tmp_path):
    database, models, feedback_runtime_service, task_planner_service, evidence_planner, _relationship, _material = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-feedback", name="Feedback Project"))
        db.add_all(
            [
                models.SheetContext(
                    id="ctx-a101",
                    project_id="proj-feedback",
                    sheet_no="A1.01",
                    sheet_name="平面布置图",
                    status="ready",
                    meta_json='{"stats":{"indexes":1}}',
                ),
                models.SheetContext(
                    id="ctx-a401",
                    project_id="proj-feedback",
                    sheet_no="A4.01",
                    sheet_name="节点详图",
                    status="ready",
                    meta_json='{"stats":{"indexes":0}}',
                ),
                models.SheetEdge(
                    id="edge-a101-a401",
                    project_id="proj-feedback",
                    source_sheet_no="A1.01",
                    target_sheet_no="A4.01",
                    edge_type="index_ref",
                    confidence=1.0,
                    evidence_json='{"mention_count":2}',
                ),
                models.FeedbackSample(
                    id="fb-dimension-1",
                    project_id="proj-feedback",
                    audit_result_id="result-1",
                    audit_version=1,
                    issue_type="dimension",
                    curation_status="accepted",
                    snapshot_json=json.dumps(
                        {
                            "false_positive_rate": 0.8,
                            "confidence_floor": 0.9,
                            "needs_secondary_review": True,
                            "severity_override": "info",
                        },
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
        db.commit()

        profile = feedback_runtime_service.load_feedback_runtime_profile(db, issue_type="dimension")
        monkeypatch.setattr(task_planner_service, "plan_with_master_llm", lambda *args, **kwargs: {"ok": False, "reason": "disabled"})
        task_planner_service.build_audit_tasks("proj-feedback", 1, db)
        dim_task = (
            db.query(models.AuditTask)
            .filter(
                models.AuditTask.project_id == "proj-feedback",
                models.AuditTask.task_type == "dimension",
            )
            .first()
        )
        plans = evidence_planner.plan_evidence_requests(
            task_type="dimension",
            source_sheet_no="A1.01",
            target_sheet_no="A4.01",
            feedback_profile=profile,
        )
    finally:
        db.close()

    assert profile["false_positive_rate"] == 0.8
    assert profile["needs_secondary_review"] is True
    assert dim_task is not None
    assert dim_task.priority == 2
    assert plans[0].pack_type.value == "focus_pack"


def test_feedback_runtime_profile_changes_worker_policies(monkeypatch, tmp_path):
    database, models, feedback_runtime_service, _task_planner, _evidence_planner, relationship_discovery, material_audit = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(
            models.FeedbackSample(
                id="fb-index-1",
                project_id="proj-feedback-worker",
                audit_result_id="result-1",
                audit_version=1,
                issue_type="index",
                curation_status="accepted",
                snapshot_json=json.dumps(
                    {
                        "false_positive_rate": 0.7,
                        "confidence_floor": 0.85,
                        "needs_secondary_review": True,
                        "severity_override": "warning",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.add(
            models.FeedbackSample(
                id="fb-material-1",
                project_id="proj-feedback-worker",
                audit_result_id="result-2",
                audit_version=1,
                issue_type="material",
                curation_status="accepted",
                snapshot_json=json.dumps(
                    {
                        "false_positive_rate": 0.75,
                        "confidence_floor": 0.8,
                        "needs_secondary_review": False,
                        "severity_override": "warning",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()

        relationship_profile = feedback_runtime_service.load_feedback_runtime_profile(db, issue_type="index")
        material_profile = feedback_runtime_service.load_feedback_runtime_profile(db, issue_type="material")
    finally:
        db.close()

    filtered = relationship_discovery.apply_relationship_runtime_policy(
        [
            {"source": "A1.01", "target": "A4.01", "confidence": 0.7},
            {"source": "A1.01", "target": "A4.02", "confidence": 0.92},
        ],
        feedback_profile=relationship_profile,
    )
    severity = material_audit.resolve_material_issue_severity(
        "error",
        feedback_profile=material_profile,
    )

    assert [item["target"] for item in filtered] == ["A4.02"]
    assert severity == "warning"
