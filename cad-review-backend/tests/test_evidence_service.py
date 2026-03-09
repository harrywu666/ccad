from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.contracts import EvidencePackType, EvidenceRequest
from services.audit_runtime.evidence_service import EvidenceService


def test_evidence_service_reuses_rendered_pack():
    calls: list[tuple[str, int, float]] = []

    def _fake_renderer(pdf_path: str, page_index: int, overlap: float, **kwargs):
        calls.append((pdf_path, page_index, overlap))
        payload = f"{pdf_path}:{page_index}".encode("utf-8")
        return {
            "full": payload + b":full",
            "top_left": payload + b":tl",
            "top_right": payload + b":tr",
            "bottom_left": payload + b":bl",
            "bottom_right": payload + b":br",
        }

    service = EvidenceService(renderer=_fake_renderer)
    request = EvidenceRequest(
        pack_type=EvidencePackType.DEEP_PACK,
        source_pdf_path="/tmp/a.pdf",
        source_page_index=2,
    )

    first = asyncio.run(service.get_evidence_pack(request))
    second = asyncio.run(service.get_evidence_pack(request))

    assert calls == [("/tmp/a.pdf", 2, 0.20)]
    assert first.images == second.images


def test_evidence_service_returns_pack_with_expected_keys():
    def _fake_renderer(pdf_path: str, page_index: int, overlap: float, **kwargs):
        payload = f"{pdf_path}:{page_index}".encode("utf-8")
        return {
            "full": payload + b":full",
            "top_left": payload + b":tl",
            "top_right": payload + b":tr",
            "bottom_left": payload + b":bl",
            "bottom_right": payload + b":br",
        }

    service = EvidenceService(renderer=_fake_renderer)

    overview = asyncio.run(
        service.get_evidence_pack(
            EvidenceRequest(
                pack_type=EvidencePackType.OVERVIEW_PACK,
                source_pdf_path="/tmp/source.pdf",
                source_page_index=0,
            )
        )
    )
    paired = asyncio.run(
        service.get_evidence_pack(
            EvidenceRequest(
                pack_type=EvidencePackType.PAIRED_OVERVIEW_PACK,
                source_pdf_path="/tmp/source.pdf",
                source_page_index=0,
                target_pdf_path="/tmp/target.pdf",
                target_page_index=1,
            )
        )
    )
    focus = asyncio.run(
        service.get_evidence_pack(
            EvidenceRequest(
                pack_type=EvidencePackType.FOCUS_PACK,
                source_pdf_path="/tmp/source.pdf",
                source_page_index=0,
            )
        )
    )
    deep = asyncio.run(
        service.get_evidence_pack(
            EvidenceRequest(
                pack_type=EvidencePackType.DEEP_PACK,
                source_pdf_path="/tmp/source.pdf",
                source_page_index=0,
            )
        )
    )

    assert set(overview.images.keys()) == {"source_full"}
    assert set(paired.images.keys()) == {"source_full", "target_full"}
    assert set(focus.images.keys()) == {"source_full", "source_top_left", "source_bottom_right"}
    assert set(deep.images.keys()) == {
        "source_full",
        "source_top_left",
        "source_top_right",
        "source_bottom_left",
        "source_bottom_right",
    }
