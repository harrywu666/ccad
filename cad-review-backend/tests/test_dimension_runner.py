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
        "services.audit_runtime.agent_runner",
        "services.audit_runtime.providers.kimi_api_provider",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit.dimension_audit"):
            sys.modules.pop(name, None)


def _load_module(monkeypatch):
    _clear_backend_modules()
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    return importlib.import_module("services.audit.dimension_audit")


def test_dimension_agent_uses_runner_and_returns_empty_on_deferred_result(monkeypatch, tmp_path):
    dimension_audit = _load_module(monkeypatch)
    runner_called = {"value": False}

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            return dimension_audit.EvidencePack(
                pack_type=request.pack_type,
                images={"source_full": b"source"},
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
            )

    class _FakeRunner:
        async def run_stream(self, request, *, should_cancel=None):  # noqa: ANN001
            runner_called["value"] = True
            return dimension_audit.RunnerTurnResult(
                provider_name="api",
                output=None,
                status="deferred",
                raw_output="broken-json",
                repair_attempts=1,
            )

    async def fake_call_kimi(**kwargs):
        raise AssertionError("runner path should be used")

    monkeypatch.setattr(dimension_audit, "get_evidence_service", lambda: _FakeEvidenceService())
    monkeypatch.setattr(dimension_audit, "_get_dimension_runner", lambda *args, **kwargs: _FakeRunner())

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
            project_id="proj-dim-runner",
            audit_version=11,
        )
    )

    assert runner_called["value"] is True
    assert result == [("A101", [], "cache-key")]
