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
        "services.audit.dimension_audit",
        "services.audit_runtime.evidence_planner",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit.dimension_audit"):
            sys.modules.pop(name, None)


def _load_module(monkeypatch):
    _clear_backend_modules()
    return importlib.import_module("services.audit.dimension_audit")


def test_dimension_worker_v2_uses_planned_evidence_pack(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")
    dimension_audit = _load_module(monkeypatch)

    captured: dict[str, object] = {}

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            captured["pack_type"] = request.pack_type.value
            return dimension_audit.EvidencePack(
                pack_type=request.pack_type,
                images={"source_full": b"source"},
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
            )

    async def fake_call_kimi(**kwargs):
        captured["images_count"] = len(kwargs.get("images") or [])
        return []

    monkeypatch.setattr(dimension_audit, "get_evidence_service", lambda: _FakeEvidenceService())

    result = asyncio.run(
        dimension_audit._execute_sheet_jobs(
            [
                {
                    "sheet_key": "A101",
                    "sheet_no": "A1.01",
                    "pdf_path": "/tmp/a101.pdf",
                    "page_index": 0,
                    "prompt": "test",
                    "cache_key": "cache-key",
                    "visual_only": False,
                }
            ],
            1,
            tmp_path,
            fake_call_kimi,
        )
    )

    assert result == [("A101", [], "cache-key")]
    assert captured["pack_type"] == "overview_pack"
    assert captured["images_count"] == 1


def test_dimension_worker_v2_emits_stream_events(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    dimension_audit = _load_module(monkeypatch)

    captured_events: list[dict[str, object]] = []

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            return dimension_audit.EvidencePack(
                pack_type=request.pack_type,
                images={
                    "source_full": b"source",
                    "source_top_left": b"source",
                    "source_top_right": b"source",
                    "source_bottom_left": b"source",
                    "source_bottom_right": b"source",
                },
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
            )

    async def fake_call_kimi(**kwargs):
        raise AssertionError("stream path should be used")

    async def fake_call_kimi_stream(**kwargs):
        await kwargs["on_delta"]("先判断这张图的尺寸语义。")
        await kwargs["on_retry"]({"attempt": 2, "reason": "429", "retry_delay_seconds": 1.0})
        return []

    monkeypatch.setattr(dimension_audit, "get_evidence_service", lambda: _FakeEvidenceService())
    monkeypatch.setattr(dimension_audit, "call_kimi_stream", fake_call_kimi_stream)
    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda *args, **kwargs: captured_events.append(kwargs),
    )

    result = asyncio.run(
        dimension_audit._execute_sheet_jobs(
            [
                {
                    "sheet_key": "A101",
                    "sheet_no": "A1.01",
                    "pdf_path": "/tmp/a101.pdf",
                    "page_index": 0,
                    "prompt": "test",
                    "cache_key": "cache-key",
                    "visual_only": False,
                }
            ],
            1,
            tmp_path,
            fake_call_kimi,
            project_id="proj-dim-stream",
            audit_version=7,
        )
    )

    assert result == [("A101", [], "cache-key")]
    assert any(
        event.get("event_kind") == "provider_stream_delta"
        and event.get("message") == "先判断这张图的尺寸语义。"
        for event in captured_events
    )
    assert any(
        event.get("event_kind") == "phase_event"
        and "第 2 次重试" in str(event.get("message") or "")
        for event in captured_events
    )


def test_dimension_worker_v2_uses_unique_subsession_key_per_sheet_job(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    dimension_audit = _load_module(monkeypatch)

    captured_meta: list[dict[str, object]] = []

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            return dimension_audit.EvidencePack(
                pack_type=request.pack_type,
                images={
                    "source_full": b"source",
                    "source_top_left": b"source",
                    "source_top_right": b"source",
                    "source_bottom_left": b"source",
                    "source_bottom_right": b"source",
                },
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
            )

    class _FakeRunner:
        async def run_stream(self, request, should_cancel=None):  # noqa: ANN001
            del should_cancel
            captured_meta.append(dict(request.meta or {}))
            return dimension_audit.RunnerTurnResult(
                provider_name="sdk",
                output=[],
                status="ok",
                raw_output="[]",
            )

    monkeypatch.setattr(dimension_audit, "get_evidence_service", lambda: _FakeEvidenceService())
    monkeypatch.setattr(
        dimension_audit,
        "_get_dimension_runner",
        lambda *args, **kwargs: _FakeRunner(),
    )

    result = asyncio.run(
        dimension_audit._execute_sheet_jobs(
            [
                {
                    "sheet_key": "A101",
                    "sheet_no": "A1.01",
                    "pdf_path": "/tmp/a101.pdf",
                    "page_index": 0,
                    "prompt": "test",
                    "cache_key": "cache-key-a",
                    "visual_only": False,
                },
                {
                    "sheet_key": "A401",
                    "sheet_no": "A4.01",
                    "pdf_path": "/tmp/a401.pdf",
                    "page_index": 1,
                    "prompt": "test-2",
                    "cache_key": "cache-key-b",
                    "visual_only": False,
                },
            ],
            2,
            tmp_path,
            lambda **kwargs: [],
            project_id="proj-dim-stream",
            audit_version=7,
        )
    )

    assert len(result) == 2
    assert [item["subsession_key"] for item in captured_meta] == [
        "sheet_semantic:A101",
        "sheet_semantic:A401",
    ]


def test_dimension_worker_v2_deduplicates_duplicate_sheet_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    dimension_audit = _load_module(monkeypatch)

    call_count = {"value": 0}

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            return dimension_audit.EvidencePack(
                pack_type=request.pack_type,
                images={
                    "source_full": b"source",
                    "source_top_left": b"source",
                    "source_top_right": b"source",
                    "source_bottom_left": b"source",
                    "source_bottom_right": b"source",
                },
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
            )

    class _FakeRunner:
        async def run_stream(self, request, should_cancel=None):  # noqa: ANN001
            del request, should_cancel
            call_count["value"] += 1
            await asyncio.sleep(0.05)
            return dimension_audit.RunnerTurnResult(
                provider_name="api",
                output=[],
                status="ok",
                raw_output="[]",
            )

    monkeypatch.setattr(dimension_audit, "get_evidence_service", lambda: _FakeEvidenceService())
    monkeypatch.setattr(
        dimension_audit,
        "_get_dimension_runner",
        lambda *args, **kwargs: _FakeRunner(),
    )

    jobs = [
        {
            "sheet_key": "A101",
            "sheet_no": "A1.01",
            "pdf_path": "/tmp/a101.pdf",
            "page_index": 0,
            "prompt": "test",
            "cache_key": "dup-sheet-cache",
            "visual_only": False,
        },
        {
            "sheet_key": "A101",
            "sheet_no": "A1.01",
            "pdf_path": "/tmp/a101.pdf",
            "page_index": 0,
            "prompt": "test",
            "cache_key": "dup-sheet-cache",
            "visual_only": False,
        },
    ]

    result = asyncio.run(
        dimension_audit._execute_sheet_jobs(
            jobs,
            2,
            tmp_path,
            lambda **kwargs: [],
            project_id="proj-dim-stream",
            audit_version=7,
        )
    )

    assert result == [
        ("A101", [], "dup-sheet-cache"),
        ("A101", [], "dup-sheet-cache"),
    ]
    assert call_count["value"] == 1


def test_dimension_worker_v2_deduplicates_duplicate_pair_jobs(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    dimension_audit = _load_module(monkeypatch)

    call_count = {"value": 0}

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            return dimension_audit.EvidencePack(
                pack_type=request.pack_type,
                images={
                    "paired_full": b"pair",
                    "source_focus": b"pair",
                    "target_focus": b"pair",
                },
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
                target_pdf_path=request.target_pdf_path,
                target_page_index=request.target_page_index,
            )

    class _FakeRunner:
        async def run_stream(self, request, should_cancel=None):  # noqa: ANN001
            del request, should_cancel
            call_count["value"] += 1
            await asyncio.sleep(0.05)
            return dimension_audit.RunnerTurnResult(
                provider_name="api",
                output=[],
                status="ok",
                raw_output="[]",
            )

    monkeypatch.setattr(dimension_audit, "get_evidence_service", lambda: _FakeEvidenceService())
    monkeypatch.setattr(
        dimension_audit,
        "_get_dimension_runner",
        lambda *args, **kwargs: _FakeRunner(),
    )

    jobs = [
        {
            "a_key": "A101",
            "b_key": "A401",
            "a_sheet_no": "A1.01",
            "a_sheet_name": "A1.01",
            "b_sheet_no": "A4.01",
            "b_sheet_name": "A4.01",
            "semantic_a": [{"id": "1"}],
            "semantic_b": [{"id": "2"}],
            "a_pdf_path": "/tmp/a101.pdf",
            "a_page_index": 0,
            "b_pdf_path": "/tmp/a401.pdf",
            "b_page_index": 1,
            "cache_key": "dup-pair-cache",
        },
        {
            "a_key": "A101",
            "b_key": "A401",
            "a_sheet_no": "A1.01",
            "a_sheet_name": "A1.01",
            "b_sheet_no": "A4.01",
            "b_sheet_name": "A4.01",
            "semantic_a": [{"id": "1"}],
            "semantic_b": [{"id": "2"}],
            "a_pdf_path": "/tmp/a101.pdf",
            "a_page_index": 0,
            "b_pdf_path": "/tmp/a401.pdf",
            "b_page_index": 1,
            "cache_key": "dup-pair-cache",
        },
    ]

    result = asyncio.run(
        dimension_audit._execute_pair_jobs(
            jobs,
            2,
            tmp_path,
            lambda **kwargs: [],
            project_id="proj-dim-stream",
            audit_version=7,
        )
    )

    assert result == {("A101", "A401"): []}
    assert call_count["value"] == 1


def test_dimension_worker_wrapper_passes_pair_filters(monkeypatch):
    dimension_audit = _load_module(monkeypatch)
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")
    captured: dict[str, object] = {}

    def fake_dimension_audit(project_id, audit_version, db, pair_filters=None, hot_sheet_registry=None):  # noqa: ANN001
        captured["pair_filters"] = pair_filters
        return []

    monkeypatch.setattr(dimension_audit, "audit_dimensions", fake_dimension_audit)

    result = dimension_audit.run_dimension_worker_wrapper(
        "proj-dim-wrapper",
        3,
        "db-session",
        review_task_schema.WorkerTaskCard(
            id="task-dim-wrapper",
            hypothesis_id="hyp-dim-wrapper",
            worker_kind="spatial_consistency",
            objective="核对两张图",
            source_sheet_no="A1.01",
            target_sheet_nos=["A4.01"],
            context={"project_id": "proj-dim-wrapper", "audit_version": 3},
        ),
    )

    assert captured["pair_filters"] == [("A1.01", "A4.01")]
    assert result.meta["compat_mode"] == "worker_wrapper"


def test_collect_dimension_pair_issues_respects_pair_filters(monkeypatch):
    dimension_audit = _load_module(monkeypatch)

    captured: dict[str, object] = {}

    class _FakeQuery:
        def filter(self, *args, **kwargs):  # noqa: ANN001
            return self

        def first(self):
            return object()

        def all(self):
            return []

    class _FakeDb:
        def query(self, model):  # noqa: ANN001
            return _FakeQuery()

    monkeypatch.setattr(dimension_audit, "_cache_dir_for_project", lambda project: Path("/tmp"))
    monkeypatch.setattr(dimension_audit, "_load_json_by_sheet", lambda *args, **kwargs: {"A101": {"sheet_no": "A1.01"}, "A401": {"sheet_no": "A4.01"}})
    monkeypatch.setattr(dimension_audit, "_load_drawing_assets", lambda *args, **kwargs: {})
    monkeypatch.setattr(dimension_audit, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(dimension_audit, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(dimension_audit, "resolve_dimension_runtime_policy", lambda *args, **kwargs: {})
    def fake_build_pairs(json_by_sheet, pair_filters, ai_edges=None):  # noqa: ANN001
        captured["pair_filters"] = pair_filters
        return []

    monkeypatch.setattr(dimension_audit, "_build_pairs", fake_build_pairs)

    issues = dimension_audit._collect_dimension_pair_issues(
        "proj-dim-filter",
        1,
        _FakeDb(),
        pair_filters=[("A1.01", "A4.01")],
    )

    assert issues == []
    assert captured["pair_filters"] == [("A1.01", "A4.01")]
