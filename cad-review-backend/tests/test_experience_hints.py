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
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.feedback_runtime_service"):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    feedback_runtime_service = importlib.import_module("services.feedback_runtime_service")
    database.init_db()
    return database, models, feedback_runtime_service


def test_experience_hint_defaults_to_advisory_when_no_samples(monkeypatch, tmp_path):
    database, models, feedback_runtime_service = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-exp-empty", name="Empty"))
        db.commit()
        profile = feedback_runtime_service.load_feedback_runtime_profile(db, issue_type="dimension")
    finally:
        db.close()

    hint = profile["experience_hint"]
    assert hint["intervention_level"] == "advisory"
    assert hint["false_positive_rate"] == 0.0


def test_experience_hint_can_reach_soft_without_worker_changes(monkeypatch, tmp_path):
    database, models, feedback_runtime_service = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-exp-soft", name="Soft"))
        db.add(
            models.FeedbackSample(
                id="fb-soft",
                project_id="proj-exp-soft",
                audit_result_id="result-soft",
                audit_version=1,
                issue_type="dimension",
                curation_status="accepted",
                snapshot_json=json.dumps(
                    {
                        "false_positive_rate": 0.72,
                        "confidence_floor": 0.88,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        profile = feedback_runtime_service.load_feedback_runtime_profile(db, issue_type="dimension")
    finally:
        db.close()

    hint = profile["experience_hint"]
    assert hint["intervention_level"] == "soft"
    assert hint["confidence_floor"] == 0.88
    assert "历史反馈" in hint["reason_template"]
