from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = ("database", "models", "services.feedback_review_queue_service")
    for name in list(sys.modules):
        if name in targets or name.startswith("services.feedback_review"):
            sys.modules.pop(name, None)


def _load_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()
    return database.SessionLocal, models


def test_feedback_thread_defaults(monkeypatch, tmp_path):
    session_local, models = _load_backend(monkeypatch, tmp_path)

    db = session_local()
    try:
        project = models.Project(id="proj-thread", name="Thread Project")
        result = models.AuditResult(
            id="result-thread",
            project_id="proj-thread",
            audit_version=3,
            type="index",
            severity="error",
            description="索引误报测试",
        )
        db.add(project)
        db.add(result)

        thread = models.FeedbackThread(
            project_id="proj-thread",
            audit_result_id="result-thread",
            audit_version=3,
        )
        db.add(thread)
        db.commit()

        assert thread.status == "open"
        assert thread.learning_decision == "pending"
        assert thread.agent_decision is None
        assert thread.result_group_id is None
    finally:
        db.close()


def test_feedback_thread_supports_messages_and_learning_records(monkeypatch, tmp_path):
    session_local, models = _load_backend(monkeypatch, tmp_path)

    db = session_local()
    try:
        project = models.Project(id="proj-thread", name="Thread Project")
        result = models.AuditResult(
            id="result-thread",
            project_id="proj-thread",
            audit_version=1,
            type="index",
            severity="error",
            description="索引误报测试",
        )
        db.add(project)
        db.add(result)

        thread = models.FeedbackThread(
            id="thread-1",
            project_id="proj-thread",
            audit_result_id="result-thread",
            audit_version=1,
        )
        db.add(thread)
        db.flush()

        db.add(
            models.FeedbackMessage(
                thread_id="thread-1",
                role="user",
                message_type="claim",
                content="这是图号别名，不该报错",
            )
        )
        db.add(
            models.FeedbackLearningRecord(
                thread_id="thread-1",
                project_id="proj-thread",
                audit_result_id="result-thread",
                decision="pending",
            )
        )
        db.commit()

        loaded_thread = db.query(models.FeedbackThread).filter_by(id="thread-1").one()
        assert len(loaded_thread.messages) == 1
        assert loaded_thread.messages[0].role == "user"
        assert len(loaded_thread.learning_records) == 1
        assert loaded_thread.learning_records[0].decision == "pending"
    finally:
        db.close()
