from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services."):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    index_audit = importlib.import_module("services.audit.index_audit")
    database.init_db()
    return database, models, index_audit


def test_index_audit_routes_ambiguous_issue_through_ai_review(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_INDEX_AI_REVIEW_ENABLED", "1")
    database, models, index_audit = _load_modules(monkeypatch, tmp_path)

    source_json = tmp_path / "source.json"
    target_json = tmp_path / "target.json"
    source_json.write_text(
        '{"indexes":[{"index_no":"D1","target_sheet":"A4.01","grid":"F11"}],"title_blocks":[]}',
        encoding="utf-8",
    )
    target_json.write_text('{"indexes":[],"title_blocks":[],"detail_titles":[]}', encoding="utf-8")

    review_calls: list[dict[str, object]] = []

    def fake_review(project_id, db, candidates, *, audit_version=None, skill_profile, feedback_profile):
        review_calls.append(
            {
                "project_id": project_id,
                "audit_version": audit_version,
                "candidate_count": len(candidates),
                "review_kind": candidates[0]["review_kind"] if candidates else None,
            }
        )
        return []

    monkeypatch.setattr(index_audit, "_review_index_issue_candidates", fake_review)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-index-ai-review", name="Index AI Review"))
        db.add_all(
            [
                models.JsonData(
                    id="json-source",
                    project_id="proj-index-ai-review",
                    sheet_no="A1.01",
                    json_path=str(source_json),
                    is_latest=1,
                ),
                models.JsonData(
                    id="json-target",
                    project_id="proj-index-ai-review",
                    sheet_no="A4.01",
                    json_path=str(target_json),
                    is_latest=1,
                ),
            ]
        )
        db.commit()

        issues = index_audit.audit_indexes("proj-index-ai-review", 1, db)

        assert issues == []
        assert review_calls == [
            {
                "project_id": "proj-index-ai-review",
                "audit_version": 1,
                "candidate_count": 1,
                "review_kind": "missing_target_index_no",
            }
        ]
    finally:
        db.close()


def test_index_audit_keeps_missing_target_sheet_on_rule_path(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_INDEX_AI_REVIEW_ENABLED", "1")
    database, models, index_audit = _load_modules(monkeypatch, tmp_path)

    source_json = tmp_path / "source.json"
    source_json.write_text(
        '{"indexes":[{"index_no":"D1","target_sheet":"A9.99","grid":"F11"}],"title_blocks":[]}',
        encoding="utf-8",
    )

    review_calls: list[int] = []

    def fake_review(project_id, db, candidates, *, audit_version=None, skill_profile, feedback_profile):
        review_calls.append(len(candidates))
        return candidates

    monkeypatch.setattr(index_audit, "_review_index_issue_candidates", fake_review)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-index-rule-path", name="Index Rule Path"))
        db.add(
            models.JsonData(
                id="json-source-rule-only",
                project_id="proj-index-rule-path",
                sheet_no="A1.01",
                json_path=str(source_json),
                is_latest=1,
            )
        )
        db.commit()

        issues = index_audit.audit_indexes("proj-index-rule-path", 1, db)

        assert len(issues) == 1
        assert "不存在该目标图" in issues[0].description
        assert issues[0].source_agent == "index_review_agent"
        assert issues[0].finding_type == "missing_ref"
        assert issues[0].review_round == 1
        assert review_calls == [0]
    finally:
        db.close()


def test_index_audit_emits_stream_events_for_ai_review(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_INDEX_AI_REVIEW_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    database, models, index_audit = _load_modules(monkeypatch, tmp_path)

    source_json = tmp_path / "source.json"
    target_json = tmp_path / "target.json"
    source_json.write_text(
        '{"indexes":[{"index_no":"D1","target_sheet":"A4.01","grid":"F11"}],"title_blocks":[]}',
        encoding="utf-8",
    )
    target_json.write_text('{"indexes":[],"title_blocks":[],"detail_titles":[]}', encoding="utf-8")

    db = database.SessionLocal()
    captured_events: list[dict[str, object]] = []
    try:
        db.add(models.Project(id="proj-index-stream", name="Index Stream"))
        db.add_all(
            [
                models.JsonData(
                    id="json-source",
                    project_id="proj-index-stream",
                    sheet_no="A1.01",
                    json_path=str(source_json),
                    is_latest=1,
                ),
                models.JsonData(
                    id="json-target",
                    project_id="proj-index-stream",
                    sheet_no="A4.01",
                    json_path=str(target_json),
                    is_latest=1,
                ),
                models.Drawing(
                    id="draw-source",
                    project_id="proj-index-stream",
                    sheet_no="A1.01",
                    png_path=str(tmp_path / "source.png"),
                    page_index=0,
                    status="matched",
                ),
                models.Drawing(
                    id="draw-target",
                    project_id="proj-index-stream",
                    sheet_no="A4.01",
                    png_path=str(tmp_path / "target.png"),
                    page_index=1,
                    status="matched",
                ),
            ]
        )
        db.commit()

        monkeypatch.setattr(index_audit, "_find_pdf_in_png_dir", lambda _path: str(tmp_path / "sheet.pdf"))

        class _FakeEvidenceService:
            async def get_evidence_pack(self, request):
                return type("Pack", (), {"images": {"source_full": b"source", "target_full": b"target"}})()

        async def fake_call_kimi_stream(**kwargs):
            await kwargs["on_delta"]("先核对索引编号，再看目标图。")
            await kwargs["on_retry"]({"attempt": 1, "reason": "5xx", "retry_delay_seconds": 2.0})
            return {"decision": "confirm", "confidence": 0.81, "reason": "能看到目标图引用"}

        monkeypatch.setattr(index_audit, "get_evidence_service", lambda: _FakeEvidenceService())
        monkeypatch.setattr(index_audit, "call_kimi_stream", fake_call_kimi_stream)
        monkeypatch.setattr(
            "services.audit_runtime.state_transitions.append_run_event",
            lambda *args, **kwargs: captured_events.append(kwargs),
        )

        issues = index_audit.audit_indexes("proj-index-stream", 4, db)

        assert len(issues) == 1
        assert any(
            event.get("event_kind") == "provider_stream_delta"
            and event.get("message") == "先核对索引编号，再看目标图。"
            for event in captured_events
        )
        assert any(
            event.get("event_kind") == "phase_event"
            and "第 1 次重试" in str(event.get("message") or "")
            for event in captured_events
        )
    finally:
        db.close()


def test_index_audit_reports_grounding_failure_to_runner(monkeypatch, tmp_path):
    database, models, index_audit = _load_modules(monkeypatch, tmp_path)

    source_json = tmp_path / "source-grounding.json"
    source_json.write_text(
        '{"indexes":[{"index_no":"D1","target_sheet":"A9.99"}],"title_blocks":[]}',
        encoding="utf-8",
    )

    captured_reports: list[object] = []
    monkeypatch.setattr(
        index_audit,
        "append_agent_status_report",
        lambda *args, **kwargs: captured_reports.append(kwargs["report"]),
    )

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-index-grounding", name="Index Grounding"))
        db.add(
            models.JsonData(
                id="json-source-grounding",
                project_id="proj-index-grounding",
                sheet_no="A1.01",
                json_path=str(source_json),
                is_latest=1,
            )
        )
        db.commit()

        issues = index_audit.audit_indexes("proj-index-grounding", 1, db)
    finally:
        db.close()

    assert issues == []
    assert len(captured_reports) == 1
    assert captured_reports[0].runner_help_request == "restart_subsession"
