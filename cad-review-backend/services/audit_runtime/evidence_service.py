"""统一证据服务层。"""

from __future__ import annotations

import asyncio
from typing import Callable, Dict, Tuple

from services.audit.image_pipeline import pdf_page_to_5images
from services.audit_runtime.contracts import EvidencePack, EvidencePackType, EvidenceRequest


RenderPayload = Dict[str, bytes]
Renderer = Callable[[str, int, float], RenderPayload]


class EvidenceService:
    """统一管理取图、缓存与去重。"""

    def __init__(self, renderer: Callable[..., RenderPayload] | None = None) -> None:
        self._renderer = renderer or pdf_page_to_5images
        self._render_cache: Dict[Tuple[str, int, Tuple[Tuple[str, float | int], ...]], RenderPayload] = {}
        self._locks: Dict[Tuple[str, int, Tuple[Tuple[str, float | int], ...]], asyncio.Lock] = {}

    async def get_evidence_pack(self, request: EvidenceRequest) -> EvidencePack:
        source_images = await self._get_page_images(
            request.source_pdf_path,
            request.source_page_index,
            request.render_options,
        )

        target_images: RenderPayload | None = None
        if request.target_pdf_path and request.target_page_index is not None:
            target_images = await self._get_page_images(
                request.target_pdf_path,
                request.target_page_index,
                request.render_options,
            )

        images = self._compose_pack_images(request.pack_type, source_images, target_images)
        return EvidencePack(
            pack_type=request.pack_type,
            images=images,
            source_pdf_path=request.source_pdf_path,
            source_page_index=request.source_page_index,
            target_pdf_path=request.target_pdf_path,
            target_page_index=request.target_page_index,
        )

    def build_request_key(self, request: EvidenceRequest) -> str:
        normalized_options = self._normalize_render_options(request.render_options)
        parts = [
            request.pack_type.value,
            str(request.source_pdf_path or "").strip(),
            str(int(request.source_page_index)),
            str(request.target_pdf_path or "").strip(),
            "" if request.target_page_index is None else str(int(request.target_page_index)),
            str(request.focus_hint or "").strip(),
            repr(normalized_options),
        ]
        return "|".join(parts)

    async def _get_page_images(
        self,
        pdf_path: str,
        page_index: int,
        render_options: Dict[str, float | int],
    ) -> RenderPayload:
        key = (pdf_path, page_index, self._normalize_render_options(render_options))
        if key in self._render_cache:
            return self._render_cache[key]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._render_cache:
                return self._render_cache[key]

            images = await asyncio.to_thread(
                self._renderer,
                pdf_path,
                page_index,
                0.20,
                **dict(render_options),
            )
            self._render_cache[key] = images
            return images

    @staticmethod
    def _normalize_render_options(render_options: Dict[str, float | int]) -> Tuple[Tuple[str, float | int], ...]:
        return tuple(sorted((render_options or {}).items()))

    @staticmethod
    def _compose_pack_images(
        pack_type: EvidencePackType,
        source_images: RenderPayload,
        target_images: RenderPayload | None,
    ) -> Dict[str, bytes]:
        if pack_type == EvidencePackType.OVERVIEW_PACK:
            return {"source_full": source_images["full"]}

        if pack_type == EvidencePackType.PAIRED_OVERVIEW_PACK:
            images = {"source_full": source_images["full"]}
            if target_images is not None:
                images["target_full"] = target_images["full"]
            return images

        if pack_type == EvidencePackType.FOCUS_PACK:
            return {
                "source_full": source_images["full"],
                "source_top_left": source_images["top_left"],
                "source_bottom_right": source_images["bottom_right"],
            }

        if pack_type == EvidencePackType.DEEP_PACK:
            return {
                "source_full": source_images["full"],
                "source_top_left": source_images["top_left"],
                "source_top_right": source_images["top_right"],
                "source_bottom_left": source_images["bottom_left"],
                "source_bottom_right": source_images["bottom_right"],
            }

        raise ValueError(f"unsupported evidence pack type: {pack_type}")


_EVIDENCE_SERVICE: EvidenceService | None = None


def get_evidence_service() -> EvidenceService:
    global _EVIDENCE_SERVICE
    if _EVIDENCE_SERVICE is None:
        _EVIDENCE_SERVICE = EvidenceService()
    return _EVIDENCE_SERVICE
