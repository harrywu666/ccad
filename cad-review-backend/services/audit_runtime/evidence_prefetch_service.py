"""证据区域预取服务。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from services.audit_runtime.contracts import EvidencePack, EvidenceRequest
from services.audit_runtime.evidence_service import EvidenceService, get_evidence_service


@dataclass
class EvidenceBatchResult:
    total_request_count: int
    unique_request_count: int
    cache_hits: int
    packs_by_key: dict[str, EvidencePack] = field(default_factory=dict)


async def prefetch_regions(
    *,
    requests: list[EvidenceRequest],
    evidence_service: EvidenceService | None = None,
) -> EvidenceBatchResult:
    service = evidence_service or get_evidence_service()
    deduped: dict[str, EvidenceRequest] = {}
    key_builder = getattr(service, "build_request_key", None)

    def _fallback_key(request: EvidenceRequest) -> str:
        render_items = tuple(sorted((request.render_options or {}).items()))
        parts = [
            request.pack_type.value,
            str(request.source_pdf_path or "").strip(),
            str(int(request.source_page_index)),
            str(request.target_pdf_path or "").strip(),
            "" if request.target_page_index is None else str(int(request.target_page_index)),
            str(request.focus_hint or "").strip(),
            repr(render_items),
        ]
        return "|".join(parts)

    for request in requests:
        key = key_builder(request) if callable(key_builder) else _fallback_key(request)
        deduped.setdefault(key, request)

    async def _load(item: tuple[str, EvidenceRequest]) -> tuple[str, EvidencePack]:
        key, request = item
        return key, await service.get_evidence_pack(request)

    loaded = await asyncio.gather(*[_load(item) for item in deduped.items()])
    return EvidenceBatchResult(
        total_request_count=len(requests),
        unique_request_count=len(deduped),
        cache_hits=max(0, len(requests) - len(deduped)),
        packs_by_key={key: pack for key, pack in loaded},
    )


__all__ = ["EvidenceBatchResult", "prefetch_regions"]
