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
        "routers.feedback",
        "services.feedback_runtime_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


def _load_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    feedback_runtime_service = importlib.import_module("services.feedback_runtime_service")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models, feedback_runtime_service


def _seed_result(session_local, models) -> None:
    db = session_local()
    try:
        db.add(models.Project(id="proj-feedback-sync", name="Feedback Sync"))
        db.add(
            models.AuditResult(
                id="result-1",
                project_id="proj-feedback-sync",
                audit_version=1,
                type="dimension",
                severity="warning",
                sheet_no_a="A1.01",
                sheet_no_b="A4.01",
                location="门洞尺寸",
                description="A1.01 与 A4.01 门洞尺寸可能不一致",
                value_a="900",
                value_b="850",
                evidence_json='{"anchors":[]}',
            )
        )
        db.commit()
    finally:
        db.close()


def test_marking_incorrect_feedback_updates_runtime_profile(monkeypatch, tmp_path):
    app, session_local, models, feedback_runtime_service = _load_app(monkeypatch, tmp_path)
    _seed_result(session_local, models)

    with TestClient(app) as client:
        response = client.patch(
            "/api/projects/proj-feedback-sync/audit/results/result-1",
            json={
                "feedback_status": "incorrect",
                "feedback_note": "这是套打误差，不应该算尺寸冲突",
            },
        )
        assert response.status_code == 200

        sample_list = client.get("/api/projects/proj-feedback-sync/feedback-samples")
        assert sample_list.status_code == 200
        sample_id = sample_list.json()[0]["id"]

        accept_resp = client.patch(
            f"/api/projects/proj-feedback-sync/feedback-samples/{sample_id}",
            json={"curation_status": "accepted"},
        )
        assert accept_resp.status_code == 200

    db = session_local()
    try:
        profile = feedback_runtime_service.load_feedback_runtime_profile(db, issue_type="dimension")
        sample = db.query(models.FeedbackSample).filter(models.FeedbackSample.id == sample_id).first()
    finally:
        db.close()

    assert profile["sample_count"] == 1
    assert profile["false_positive_rate"] > 0
    assert sample is not None
    assert sample.user_note == "这是套打误差，不应该算尺寸冲突"


def test_confirming_issue_does_not_create_false_positive_sample(monkeypatch, tmp_path):
    app, session_local, models, feedback_runtime_service = _load_app(monkeypatch, tmp_path)
    _seed_result(session_local, models)

    with TestClient(app) as client:
        response = client.patch(
            "/api/projects/proj-feedback-sync/audit/results/result-1",
            json={"is_resolved": True},
        )
        assert response.status_code == 200

    db = session_local()
    try:
        samples = db.query(models.FeedbackSample).all()
        profile = feedback_runtime_service.load_feedback_runtime_profile(db, issue_type="dimension")
    finally:
        db.close()

    assert samples == []
    assert profile["sample_count"] == 0
