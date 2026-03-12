from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "services.audit.material_audit",
        "services.audit_runtime.evidence_planner",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit.material_audit"):
            sys.modules.pop(name, None)


def _load_module(monkeypatch):
    _clear_backend_modules()
    return importlib.import_module("services.audit.material_audit")


def test_material_worker_v2_limits_concurrency_and_uses_planned_pack(monkeypatch):
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")
    monkeypatch.setenv("MATERIAL_AGENT_CONCURRENCY", "1")
    material_audit = _load_module(monkeypatch)

    captured = {"pack_types": [], "max_active": 0}
    state = {"active": 0}

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            captured["pack_types"].append(request.pack_type.value)
            return material_audit.EvidencePack(
                pack_type=request.pack_type,
                images={
                    "source_full": b"source",
                    "source_top_left": b"tl",
                    "source_bottom_right": b"br",
                },
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
            )

    async def fake_review(**kwargs):
        state["active"] += 1
        captured["max_active"] = max(captured["max_active"], state["active"])
        await asyncio.sleep(0.01)
        state["active"] -= 1
        return []

    monkeypatch.setattr(material_audit, "get_evidence_service", lambda: _FakeEvidenceService())

    asyncio.run(
        material_audit._run_material_ai_reviews_bounded(
            [
                {
                    "sheet_no": "A1.01",
                    "material_table": [],
                    "material_used": [],
                    "pdf_path": "/tmp/a101.pdf",
                    "page_index": 0,
                },
                {
                    "sheet_no": "A1.02",
                    "material_table": [],
                    "material_used": [],
                    "pdf_path": "/tmp/a102.pdf",
                    "page_index": 1,
                },
            ],
            fake_review,
        )
    )

    assert captured["pack_types"] == ["focus_pack", "focus_pack"]
    assert captured["max_active"] == 1


def test_material_worker_v2_emits_stream_events(monkeypatch):
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    monkeypatch.setenv("MATERIAL_AGENT_CONCURRENCY", "1")
    material_audit = _load_module(monkeypatch)

    captured_events: list[dict[str, object]] = []

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            return material_audit.EvidencePack(
                pack_type=request.pack_type,
                images={"source_full": b"source"},
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
            )

    async def fake_review(**kwargs):
        return await material_audit._run_material_ai_review(**kwargs)

    async def fake_call_kimi_stream(**kwargs):
        await kwargs["on_delta"]("先对照材料表，再看图面标注。")
        await kwargs["on_retry"]({"attempt": 1, "reason": "5xx", "retry_delay_seconds": 2.0})
        return []

    monkeypatch.setattr(material_audit, "get_evidence_service", lambda: _FakeEvidenceService())
    monkeypatch.setattr(material_audit, "call_kimi_stream", fake_call_kimi_stream)
    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda *args, **kwargs: captured_events.append(kwargs),
    )

    asyncio.run(
        material_audit._run_material_ai_reviews_bounded(
            [
                {
                    "project_id": "proj-mat-stream",
                    "audit_version": 5,
                    "sheet_no": "A1.01",
                    "material_table": [],
                    "material_used": [],
                    "pdf_path": "/tmp/a101.pdf",
                    "page_index": 0,
                },
            ],
            fake_review,
        )
    )

    assert any(
        event.get("event_kind") == "provider_stream_delta"
        and event.get("message") == "先对照材料表，再看图面标注。"
        for event in captured_events
    )
    assert any(
        event.get("event_kind") == "phase_event"
        and "第 1 次重试" in str(event.get("message") or "")
        for event in captured_events
    )


def test_material_worker_wrapper_passes_sheet_filters(monkeypatch):
    material_audit = _load_module(monkeypatch)
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")
    captured: dict[str, object] = {}

    def fake_material_audit(project_id, audit_version, db, sheet_filters=None, hot_sheet_registry=None):  # noqa: ANN001
        captured["sheet_filters"] = sheet_filters
        return []

    monkeypatch.setattr(material_audit, "audit_materials", fake_material_audit)

    result = material_audit.run_material_worker_wrapper(
        "proj-mat-wrapper",
        4,
        "db-session",
        review_task_schema.WorkerTaskCard(
            id="task-mat-wrapper",
            hypothesis_id="hyp-mat-wrapper",
            worker_kind="material_semantic_consistency",
            objective="核对 A1.01 材料",
            source_sheet_no="A1.01",
            context={"project_id": "proj-mat-wrapper", "audit_version": 4},
        ),
    )

    assert captured["sheet_filters"] == ["A1.01"]
    assert result.meta["compat_mode"] == "worker_wrapper"


def test_collect_material_rule_issues_and_ai_jobs_respects_sheet_filters(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    material_audit = _load_module(monkeypatch)
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()

    source_a = tmp_path / "a101.json"
    source_b = tmp_path / "a102.json"
    source_a.write_text(
        '{"material_table":[{"code":"M01","name":"石材"}],"materials":[{"code":"M01","name":"木饰面"}]}',
        encoding="utf-8",
    )
    source_b.write_text(
        '{"material_table":[{"code":"M02","name":"乳胶漆"}],"materials":[{"code":"M02","name":"乳胶漆"}]}',
        encoding="utf-8",
    )

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-mat-filter", name="Material Filter"))
        db.add_all(
            [
                models.JsonData(
                    id="json-mat-a",
                    project_id="proj-mat-filter",
                    sheet_no="A1.01",
                    json_path=str(source_a),
                    is_latest=1,
                ),
                models.JsonData(
                    id="json-mat-b",
                    project_id="proj-mat-filter",
                    sheet_no="A1.02",
                    json_path=str(source_b),
                    is_latest=1,
                ),
            ]
        )
        db.commit()

        rule_issues, ai_jobs = material_audit._collect_material_rule_issues_and_ai_jobs(
            "proj-mat-filter",
            1,
            db,
            sheet_filters=["A1.01"],
        )
    finally:
        db.close()

    assert len(rule_issues) == 1
    assert rule_issues[0].sheet_no_a == "A1.01"
    assert len(ai_jobs) == 1
    assert ai_jobs[0]["sheet_no"] == "A1.01"
