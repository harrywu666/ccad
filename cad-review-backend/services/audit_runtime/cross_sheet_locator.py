"""LLM-first 跨图定位服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from services.audit_runtime.cross_sheet_index import AnchorRegion, CrossSheetCandidateIndex
from services.audit_runtime.hot_sheet_registry import HotSheetRegistry


@dataclass(frozen=True)
class AnchorPair:
    source_sheet_no: str
    target_sheet_no: str
    source_bbox_pct: dict[str, float]
    target_bbox_pct: dict[str, float]
    confidence: float


def _match_regions(regions: list[AnchorRegion], label_hint: str) -> list[AnchorRegion]:
    normalized_hint = str(label_hint or "").strip()
    if not normalized_hint:
        return list(regions)
    exact = [item for item in regions if normalized_hint in item.label]
    return exact or list(regions)


def _build_candidate_pairs(
    *,
    source_sheet_no: str,
    target_sheet_nos: list[str],
    anchor_hint: dict[str, Any],
    candidate_index: CrossSheetCandidateIndex,
) -> list[dict[str, Any]]:
    label_hint = str((anchor_hint or {}).get("label") or "").strip()
    source_regions = _match_regions(candidate_index.get_regions(source_sheet_no), label_hint)
    if not source_regions:
        return []
    source_region = source_regions[0]

    pairs: list[dict[str, Any]] = []
    for target_sheet_no in target_sheet_nos:
        target_regions = _match_regions(candidate_index.get_regions(target_sheet_no), label_hint)
        if not target_regions:
            continue
        target_region = target_regions[0]
        pairs.append(
            {
                "source_sheet_no": source_sheet_no,
                "target_sheet_no": target_sheet_no,
                "source_bbox_pct": dict(source_region.bbox_pct),
                "target_bbox_pct": dict(target_region.bbox_pct),
                "confidence": 0.75,
            }
        )
    return pairs


def locate_across_sheets(
    *,
    source_sheet_no: str,
    target_sheet_nos: list[str],
    anchor_hint: dict[str, Any],
    candidate_index: CrossSheetCandidateIndex,
    llm_runner: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
    hot_sheet_registry: HotSheetRegistry | None = None,
) -> list[AnchorPair]:
    candidate_pairs = _build_candidate_pairs(
        source_sheet_no=source_sheet_no,
        target_sheet_nos=target_sheet_nos,
        anchor_hint=anchor_hint,
        candidate_index=candidate_index,
    )
    payload = {
        "source_sheet_no": source_sheet_no,
        "target_sheet_nos": list(target_sheet_nos),
        "anchor_hint": dict(anchor_hint or {}),
        "candidate_pairs": candidate_pairs,
    }
    raw_pairs = llm_runner(payload) if llm_runner else candidate_pairs
    pairs = [
        AnchorPair(
            source_sheet_no=str(item.get("source_sheet_no") or source_sheet_no).strip(),
            target_sheet_no=str(item.get("target_sheet_no") or "").strip(),
            source_bbox_pct=dict(item.get("source_bbox_pct") or {}),
            target_bbox_pct=dict(item.get("target_bbox_pct") or {}),
            confidence=float(item.get("confidence") or 0.0),
        )
        for item in list(raw_pairs or [])
        if str(item.get("target_sheet_no") or "").strip()
    ]
    if hot_sheet_registry and pairs:
        hot_sheet_registry.publish_many(
            [item.target_sheet_no for item in pairs],
            finding_type="cross_sheet_anchor",
            confidence=max(item.confidence for item in pairs),
            source_agent="cross_sheet_locator",
        )
    return pairs


__all__ = ["AnchorPair", "locate_across_sheets"]
