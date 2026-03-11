from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = ("services.audit.dimension_audit",)
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit.dimension_audit"):
            sys.modules.pop(name, None)


def _load_module(monkeypatch):
    _clear_backend_modules()
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    return importlib.import_module("services.audit.dimension_audit")


def test_dimension_pair_jobs_keep_partial_progress_when_one_job_crashes(monkeypatch, tmp_path):
    dimension_audit = _load_module(monkeypatch)

    captured_reports = []

    class _FakeRunner:
        async def run_stream(self, request, should_cancel):
            if request.meta.get("source_sheet_no") == "A1.01":
                raise RuntimeError("pair worker boom")
            return dimension_audit.RunnerTurnResult(
                provider_name="sdk",
                output=[{"id": "ok"}],
                status="ok",
                raw_output='[{"id":"ok"}]',
                events=[],
            )

    monkeypatch.setattr(dimension_audit, "_get_dimension_runner", lambda *args, **kwargs: _FakeRunner())
    monkeypatch.setattr(dimension_audit, "_dimension_stream_enabled", lambda: True)
    monkeypatch.setattr(dimension_audit, "_save_cache_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(dimension_audit, "append_agent_status_report", lambda *args, **kwargs: captured_reports.append(kwargs["report"]))
    monkeypatch.setattr(dimension_audit, "resolve_stage_system_prompt_with_skills", lambda *args, **kwargs: "system")

    results = asyncio.run(
        dimension_audit._execute_pair_jobs(  # type: ignore[attr-defined]
            [
                {
                    "a_key": "A101",
                    "b_key": "A102",
                    "a_sheet_no": "A1.01",
                    "a_sheet_name": "平面图",
                    "b_sheet_no": "A1.02",
                    "b_sheet_name": "立面图",
                    "semantic_a": [{"id": "a"}],
                    "semantic_b": [{"id": "b"}],
                    "a_pdf_path": "",
                    "a_page_index": 0,
                    "b_pdf_path": "",
                    "b_page_index": 0,
                    "cache_key": "pair-a",
                },
                {
                    "a_key": "B101",
                    "b_key": "B102",
                    "a_sheet_no": "B1.01",
                    "a_sheet_name": "平面图",
                    "b_sheet_no": "B1.02",
                    "b_sheet_name": "立面图",
                    "semantic_a": [{"id": "a"}],
                    "semantic_b": [{"id": "b"}],
                    "a_pdf_path": "",
                    "a_page_index": 0,
                    "b_pdf_path": "",
                    "b_page_index": 0,
                    "cache_key": "pair-b",
                },
            ],
            pair_concurrency=2,
            cache_dir=tmp_path,
            call_kimi=None,
            project_id="proj-resilience",
            audit_version=1,
        )
    )

    assert results == {("B101", "B102"): [{"id": "ok"}]}
    assert len(captured_reports) == 1
    assert captured_reports[0].blocking_issues[0]["kind"] == "job_failed"
    assert captured_reports[0].runner_help_request == "restart_subsession"


def test_dimension_sheet_jobs_keep_partial_progress_when_one_job_crashes(monkeypatch, tmp_path):
    dimension_audit = _load_module(monkeypatch)

    captured_reports = []

    class _FakePack:
        images = {
            "source_full": b"full",
            "source_top_left": b"tl",
            "source_top_right": b"tr",
            "source_bottom_left": b"bl",
            "source_bottom_right": b"br",
        }

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            return _FakePack()

    class _FakeRunner:
        async def run_stream(self, request, should_cancel):
            if request.meta.get("sheet_no") == "A1.01":
                raise RuntimeError("sheet worker boom")
            return dimension_audit.RunnerTurnResult(
                provider_name="sdk",
                output=[{"id": "ok"}],
                status="ok",
                raw_output='[{"id":"ok"}]',
                events=[],
            )

    monkeypatch.setattr(dimension_audit, "get_evidence_service", lambda: _FakeEvidenceService())
    monkeypatch.setattr(dimension_audit, "_get_dimension_runner", lambda *args, **kwargs: _FakeRunner())
    monkeypatch.setattr(dimension_audit, "_dimension_stream_enabled", lambda: True)
    monkeypatch.setattr(dimension_audit, "_dimension_v2_enabled", lambda: False)
    monkeypatch.setattr(dimension_audit, "_save_cache_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(dimension_audit, "append_agent_status_report", lambda *args, **kwargs: captured_reports.append(kwargs["report"]))
    monkeypatch.setattr(dimension_audit, "resolve_stage_system_prompt_with_skills", lambda *args, **kwargs: "system")

    results = asyncio.run(
        dimension_audit._execute_sheet_jobs(  # type: ignore[attr-defined]
            [
                {
                    "sheet_key": "A101",
                    "sheet_no": "A1.01",
                    "pdf_path": "/tmp/a.pdf",
                    "page_index": 0,
                    "prompt": "prompt-a",
                    "cache_key": "sheet-a",
                    "visual_only": False,
                },
                {
                    "sheet_key": "B101",
                    "sheet_no": "B1.01",
                    "pdf_path": "/tmp/b.pdf",
                    "page_index": 0,
                    "prompt": "prompt-b",
                    "cache_key": "sheet-b",
                    "visual_only": False,
                },
            ],
            sheet_concurrency=2,
            cache_dir=tmp_path,
            call_kimi=None,
            project_id="proj-resilience",
            audit_version=1,
        )
    )

    assert results == [("B101", [{"id": "ok"}], "sheet-b")]
    assert len(captured_reports) == 1
    assert captured_reports[0].blocking_issues[0]["kind"] == "job_failed"
    assert captured_reports[0].runner_help_request == "restart_subsession"
