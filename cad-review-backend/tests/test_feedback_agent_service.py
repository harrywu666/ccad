from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = ("database", "models", "services.feedback_agent_service", "services.feedback_agent_types", "services.feedback_review_queue_service")
    for name in list(sys.modules):
        if name in targets or name.startswith("services.feedback_agent") or name.startswith("services.feedback_review"):
            sys.modules.pop(name, None)


def _load_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "rule")
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    service = importlib.import_module("services.feedback_agent_service")
    database.init_db()
    return database.SessionLocal, models, service


def test_feedback_agent_returns_follow_up_when_context_is_insufficient(monkeypatch, tmp_path):
    _, models, service = _load_backend(monkeypatch, tmp_path)

    thread = models.FeedbackThread(
        id="thread-1",
        project_id="proj-1",
        audit_result_id="result-1",
        audit_version=1,
        status="open",
    )
    result = models.AuditResult(
        id="result-1",
        project_id="proj-1",
        audit_version=1,
        type="index",
        severity="error",
        rule_id="index_alias_rule",
        confidence=0.52,
        description="索引指向疑似不一致",
    )

    decision = service.decide_feedback_thread(
        thread=thread,
        audit_result=result,
        recent_messages=[{"role": "user", "content": "这是误报"}],
        similar_cases=[],
    )

    assert decision.status == "agent_needs_user_input"
    assert decision.follow_up_question
    assert decision.needs_learning_gate is False


def test_query_similar_feedback_cases_uses_rule_and_issue_type(monkeypatch, tmp_path):
    session_local, models, service = _load_backend(monkeypatch, tmp_path)

    db = session_local()
    try:
        project = models.Project(id="proj-1", name="Proj 1")
        result = models.AuditResult(
            id="result-1",
            project_id="proj-1",
            audit_version=1,
            type="index",
            severity="error",
            rule_id="index_alias_rule",
            description="索引指向疑似不一致",
        )
        thread = models.FeedbackThread(
            id="thread-1",
            project_id="proj-1",
            audit_result_id="result-1",
            audit_version=1,
        )
        db.add_all([project, result, thread])
        db.flush()

        now = datetime.now()
        db.add_all(
            [
                models.FeedbackLearningRecord(
                    id="lr-1",
                    thread_id="thread-1",
                    project_id="proj-1",
                    audit_result_id="result-1",
                    rule_id="index_alias_rule",
                    issue_type="index",
                    decision="accepted_for_learning",
                    evidence_score=0.66,
                    created_at=now - timedelta(minutes=3),
                ),
                models.FeedbackLearningRecord(
                    id="lr-2",
                    thread_id="thread-1",
                    project_id="proj-1",
                    audit_result_id="result-1",
                    rule_id="index_alias_rule",
                    issue_type="index",
                    decision="accepted_for_learning",
                    evidence_score=0.92,
                    created_at=now - timedelta(minutes=2),
                ),
                models.FeedbackLearningRecord(
                    id="lr-3",
                    thread_id="thread-1",
                    project_id="proj-1",
                    audit_result_id="result-1",
                    rule_id="index_alias_rule",
                    issue_type="index",
                    decision="accepted_for_learning",
                    evidence_score=0.92,
                    created_at=now - timedelta(minutes=1),
                ),
                models.FeedbackLearningRecord(
                    id="lr-4",
                    thread_id="thread-1",
                    project_id="proj-1",
                    audit_result_id="result-1",
                    rule_id="index_alias_rule",
                    issue_type="index",
                    decision="accepted_for_learning",
                    evidence_score=0.50,
                    created_at=now,
                ),
                models.FeedbackLearningRecord(
                    id="lr-5",
                    thread_id="thread-1",
                    project_id="proj-1",
                    audit_result_id="result-1",
                    rule_id="other_rule",
                    issue_type="index",
                    decision="accepted_for_learning",
                    evidence_score=0.99,
                    created_at=now,
                ),
                models.FeedbackLearningRecord(
                    id="lr-6",
                    thread_id="thread-1",
                    project_id="proj-1",
                    audit_result_id="result-1",
                    rule_id="index_alias_rule",
                    issue_type="dimension",
                    decision="accepted_for_learning",
                    evidence_score=0.99,
                    created_at=now,
                ),
            ]
        )
        db.commit()

        similar_cases = service.query_similar_feedback_cases(
            db,
            rule_id="index_alias_rule",
            issue_type="index",
        )
    finally:
        db.close()

    assert [item["id"] for item in similar_cases] == ["lr-3", "lr-2", "lr-1"]
