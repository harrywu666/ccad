from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


TINY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.feedback_agent_service",
        "services.feedback_agent_types",
        "services.feedback_agent_prompt",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.feedback_agent"):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    service = importlib.import_module("services.feedback_agent_service")
    database.init_db()
    return database, models, service


def _seed_thread(database, models):
    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-feedback-llm", name="Feedback LLM Project"))
        result = models.AuditResult(
            id="result-feedback-llm",
            project_id="proj-feedback-llm",
            audit_version=1,
            type="index",
            severity="error",
            rule_id="index_alias_rule",
            confidence=0.52,
            description="索引指向疑似不一致",
        )
        thread = models.FeedbackThread(
            id="thread-feedback-llm",
            project_id="proj-feedback-llm",
            audit_result_id="result-feedback-llm",
            audit_version=1,
            status="agent_reviewing",
            learning_decision="pending",
            rule_id="index_alias_rule",
            issue_type="index",
        )
        db.add(result)
        db.add(thread)
        db.commit()
        db.refresh(result)
        db.refresh(thread)
        db.expunge(result)
        db.expunge(thread)
        return thread, result
    finally:
        db.close()


def _seed_thread_with_attachment(database, models, tmp_path: Path):
    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-feedback-llm-img", name="Feedback LLM Image Project"))
        result = models.AuditResult(
            id="result-feedback-llm-img",
            project_id="proj-feedback-llm-img",
            audit_version=1,
            type="index",
            severity="error",
            rule_id="index_alias_rule",
            confidence=0.52,
            description="索引指向疑似不一致",
        )
        thread = models.FeedbackThread(
            id="thread-feedback-llm-img",
            project_id="proj-feedback-llm-img",
            audit_result_id="result-feedback-llm-img",
            audit_version=1,
            status="agent_reviewing",
            learning_decision="pending",
            rule_id="index_alias_rule",
            issue_type="index",
        )
        message = models.FeedbackMessage(
            id="message-feedback-llm-img",
            thread_id="thread-feedback-llm-img",
            role="user",
            message_type="claim",
            content="请结合图片一起判断",
        )
        db.add_all([result, thread, message])
        db.flush()
        image_path = tmp_path / "proof-1.png"
        image_path.write_bytes(TINY_PNG_BYTES)
        attachment = models.FeedbackMessageAttachment(
            id="attachment-feedback-llm-img",
            project_id="proj-feedback-llm-img",
            thread_id="thread-feedback-llm-img",
            message_id="message-feedback-llm-img",
            file_name="proof-1.png",
            mime_type="image/png",
            file_size=len(TINY_PNG_BYTES),
            storage_path=str(image_path),
        )
        db.add(attachment)
        db.commit()
        db.refresh(result)
        db.refresh(thread)
        db.expunge(result)
        db.expunge(thread)
        return thread, result
    finally:
        db.close()


def test_feedback_agent_prefers_llm_response(monkeypatch, tmp_path):
    database, models, service = _load_modules(monkeypatch, tmp_path)
    thread, result = _seed_thread(database, models)
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "hybrid")
    monkeypatch.setenv("FEEDBACK_AGENT_PROVIDER", "sdk")

    class _FakeProvider:
        async def run_once(self, request, subsession):  # noqa: ANN001
            assert request.agent_key == "feedback_agent"
            assert request.max_tokens == 1200
            assert "误报反馈 Agent" in request.system_prompt
            assert "只返回 JSON 对象" in request.user_prompt
            assert subsession.session_key == f"feedback-thread:{thread.id}"
            return SimpleNamespace(
                output={
                    "status": "resolved_incorrect",
                    "user_reply": "这更像项目别名导致的误报。",
                    "summary": "项目别名误报。",
                    "confidence": 0.91,
                    "reason_codes": ["alias"],
                    "needs_learning_gate": True,
                    "suggested_learning_decision": "record_only",
                    "follow_up_question": None,
                    "evidence_gaps": [],
                },
                raw_output="",
            )

    monkeypatch.setattr(service, "_build_feedback_agent_provider", lambda: _FakeProvider())

    decision = service.decide_feedback_thread(
        thread=thread,
        audit_result=result,
        recent_messages=[{"role": "user", "content": "项目里一直叫 A06.01a"}],
        similar_cases=[],
    )

    assert decision.status == "resolved_incorrect"
    assert decision.suggested_learning_decision == "record_only"
    assert decision.confidence == 0.91


def test_feedback_agent_hybrid_mode_raises_when_sdk_provider_fails(monkeypatch, tmp_path):
    database, models, service = _load_modules(monkeypatch, tmp_path)
    thread, result = _seed_thread(database, models)
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "hybrid")
    monkeypatch.setenv("FEEDBACK_AGENT_PROVIDER", "sdk")

    class _BrokenProvider:
        async def run_once(self, request, subsession):  # noqa: ANN001
            raise RuntimeError("llm unavailable")

    monkeypatch.setattr(service, "_build_feedback_agent_provider", lambda: _BrokenProvider())

    try:
        service.decide_feedback_thread(
            thread=thread,
            audit_result=result,
            recent_messages=[{"role": "user", "content": "项目里一直叫 A06.01a"}],
            similar_cases=[],
        )
    except RuntimeError as exc:
        assert "llm unavailable" in str(exc)
    else:
        raise AssertionError("expected hybrid mode to raise when sdk provider fails")


def test_feedback_agent_llm_mode_raises_without_fallback(monkeypatch, tmp_path):
    database, models, service = _load_modules(monkeypatch, tmp_path)
    thread, result = _seed_thread(database, models)
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "llm")
    monkeypatch.setenv("FEEDBACK_AGENT_PROVIDER", "sdk")

    class _BrokenProvider:
        async def run_once(self, request, subsession):  # noqa: ANN001
            raise RuntimeError("llm unavailable")

    monkeypatch.setattr(service, "_build_feedback_agent_provider", lambda: _BrokenProvider())

    try:
        service.decide_feedback_thread(
            thread=thread,
            audit_result=result,
            recent_messages=[{"role": "user", "content": "项目里一直叫 A06.01a"}],
            similar_cases=[],
        )
    except RuntimeError as exc:
        assert "llm unavailable" in str(exc)
    else:
        raise AssertionError("expected llm mode to raise when model call fails")


def test_feedback_agent_repairs_sdk_raw_output(monkeypatch, tmp_path):
    database, models, service = _load_modules(monkeypatch, tmp_path)
    thread, result = _seed_thread(database, models)
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "llm")
    monkeypatch.setenv("FEEDBACK_AGENT_PROVIDER", "sdk")

    class _FenceProvider:
        async def run_once(self, request, subsession):  # noqa: ANN001
            return SimpleNamespace(
                output=None,
                raw_output=(
                    "```json\n"
                    '{"status":"resolved_incorrect","user_reply":"这是项目别名造成的误报。","summary":"项目别名误报。","confidence":0.88,"reason_codes":["alias"],"needs_learning_gate":true,"suggested_learning_decision":"record_only","follow_up_question":null,"evidence_gaps":[]}\n'
                    "```"
                ),
            )

    monkeypatch.setattr(service, "_build_feedback_agent_provider", lambda: _FenceProvider())

    decision = service.decide_feedback_thread(
        thread=thread,
        audit_result=result,
        recent_messages=[{"role": "user", "content": "项目里一直叫 A06.01a"}],
        similar_cases=[],
    )

    assert decision.status == "resolved_incorrect"
    assert decision.suggested_learning_decision == "record_only"


def test_feedback_agent_passes_image_attachments_to_sdk(monkeypatch, tmp_path):
    database, models, service = _load_modules(monkeypatch, tmp_path)
    thread, result = _seed_thread_with_attachment(database, models, tmp_path)
    monkeypatch.setenv("FEEDBACK_AGENT_MODE", "llm")
    monkeypatch.setenv("FEEDBACK_AGENT_PROVIDER", "sdk")

    class _FakeProvider:
        async def run_once(self, request, subsession):  # noqa: ANN001
            assert len(request.images) == 1
            assert request.images[0] == TINY_PNG_BYTES
            return SimpleNamespace(
                output={
                    "status": "resolved_incorrect",
                    "user_reply": "我结合图片看了，这更像误报。",
                    "summary": "图片辅助判断后更像误报。",
                    "confidence": 0.9,
                    "reason_codes": ["image_supported"],
                    "needs_learning_gate": True,
                    "suggested_learning_decision": "record_only",
                    "follow_up_question": None,
                    "evidence_gaps": [],
                },
                raw_output="",
            )

    monkeypatch.setattr(service, "_build_feedback_agent_provider", lambda: _FakeProvider())

    decision = service.decide_feedback_thread(
        thread=thread,
        audit_result=result,
        recent_messages=[{"role": "user", "content": "请结合图片一起判断"}],
        similar_cases=[],
        image_payloads=[TINY_PNG_BYTES],
    )

    assert decision.status == "resolved_incorrect"
