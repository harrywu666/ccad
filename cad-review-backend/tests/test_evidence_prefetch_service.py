from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.contracts import EvidencePack, EvidencePackType, EvidenceRequest


class _FakeEvidenceService:
    def __init__(self) -> None:
        self.calls = 0

    async def get_evidence_pack(self, request: EvidenceRequest) -> EvidencePack:
        self.calls += 1
        return EvidencePack(
            pack_type=request.pack_type,
            images={"source_full": b"png"},
            source_pdf_path=request.source_pdf_path,
            source_page_index=request.source_page_index,
            target_pdf_path=request.target_pdf_path,
            target_page_index=request.target_page_index,
        )


def test_evidence_prefetch_dedupes_same_region_requests():
    evidence_prefetch_service = importlib.import_module("services.audit_runtime.evidence_prefetch_service")

    req1 = EvidenceRequest(
        pack_type=EvidencePackType.FOCUS_PACK,
        source_pdf_path="/tmp/demo-a.pdf",
        source_page_index=1,
        focus_hint="3.000 标高",
        render_options={"dpi": 144},
    )
    req2 = EvidenceRequest(
        pack_type=EvidencePackType.FOCUS_PACK,
        source_pdf_path="/tmp/demo-b.pdf",
        source_page_index=2,
        focus_hint="3.000 标高",
        render_options={"dpi": 144},
    )
    service = _FakeEvidenceService()

    batch = asyncio.run(
        evidence_prefetch_service.prefetch_regions(
            requests=[req1, req1, req2],
            evidence_service=service,
        )
    )

    assert batch.cache_hits >= 1
    assert batch.unique_request_count == 2
    assert service.calls == 2
