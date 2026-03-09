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
