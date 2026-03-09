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
