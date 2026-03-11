from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_modules() -> None:
    targets = (
        "database",
        "models",
        "services.feedback_runtime_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.feedback_runtime_service"):
            sys.modules.pop(name, None)


def _load_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    service = importlib.import_module("services.feedback_runtime_service")
    database.init_db()
    return database.SessionLocal, models, service


def test_feedback_samples_only_sync_from_accepted_learning_records(monkeypatch, tmp_path):
    session_local, models, service = _load_backend(monkeypatch, tmp_path)

    db = session_local()
    try:
        project = models.Project(id="proj-sync-v2", name="Sync V2")
        result = models.AuditResult(
            id="result-sync-v2",
            project_id="proj-sync-v2",
            audit_version=1,
            type="index",
            severity="error",
            rule_id="index_alias_rule",
            description="索引指向疑似不一致",
        )
        thread = models.FeedbackThread(
            id="thread-sync-v2",
            project_id="proj-sync-v2",
            audit_result_id="result-sync-v2",
            audit_version=1,
        )
        db.add_all([project, result, thread])
        db.flush()

        accepted_record = models.FeedbackLearningRecord(
            id="lr-accepted",
            thread_id="thread-sync-v2",
            project_id="proj-sync-v2",
            audit_result_id="result-sync-v2",
            rule_id="index_alias_rule",
            issue_type="index",
            decision="accepted_for_learning",
            evidence_score=0.91,
            similar_case_count=3,
            reusability_score=0.88,
        )
        db.add(accepted_record)
        db.commit()

        service.sync_feedback_sample_from_learning_record(
            db,
            learning_record=accepted_record,
            audit_result=result,
            user_note="项目里一直把 A06.01a 写成 A06.01",
        )
        db.commit()

        samples = db.query(models.FeedbackSample).all()
    finally:
        db.close()

    assert len(samples) == 1
    assert samples[0].audit_result_id == "result-sync-v2"
    assert samples[0].curation_status == "accepted"


def test_record_only_learning_record_does_not_create_feedback_sample(monkeypatch, tmp_path):
    session_local, models, service = _load_backend(monkeypatch, tmp_path)

    db = session_local()
    try:
        project = models.Project(id="proj-sync-v2", name="Sync V2")
        result = models.AuditResult(
            id="result-sync-v2",
            project_id="proj-sync-v2",
            audit_version=1,
            type="index",
            severity="error",
            rule_id="index_alias_rule",
            description="索引指向疑似不一致",
        )
        thread = models.FeedbackThread(
            id="thread-sync-v2",
            project_id="proj-sync-v2",
            audit_result_id="result-sync-v2",
            audit_version=1,
        )
        db.add_all([project, result, thread])
        db.flush()

        record_only = models.FeedbackLearningRecord(
            id="lr-record-only",
            thread_id="thread-sync-v2",
            project_id="proj-sync-v2",
            audit_result_id="result-sync-v2",
            rule_id="index_alias_rule",
            issue_type="index",
            decision="record_only",
            evidence_score=0.82,
            similar_case_count=0,
            reusability_score=0.2,
        )
        db.add(record_only)
        db.commit()

        service.sync_feedback_sample_from_learning_record(
            db,
            learning_record=record_only,
            audit_result=result,
            user_note="只是项目特例",
        )
        db.commit()

        samples = db.query(models.FeedbackSample).all()
    finally:
        db.close()

    assert samples == []
