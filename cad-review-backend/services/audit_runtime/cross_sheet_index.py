"""跨图定位候选索引。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnchorRegion:
    sheet_no: str
    label: str
    bbox_pct: dict[str, float]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrossSheetCandidateIndex:
    regions_by_sheet: dict[str, list[AnchorRegion]]

    def get_regions(self, sheet_no: str) -> list[AnchorRegion]:
        return list(self.regions_by_sheet.get(str(sheet_no or "").strip(), []))


def build_cross_sheet_index(*, sheet_regions: list[dict[str, Any]]) -> CrossSheetCandidateIndex:
    regions_by_sheet: dict[str, list[AnchorRegion]] = {}
    for item in sheet_regions:
        sheet_no = str(item.get("sheet_no") or "").strip()
        if not sheet_no:
            continue
        regions_by_sheet.setdefault(sheet_no, []).append(
            AnchorRegion(
                sheet_no=sheet_no,
                label=str(item.get("label") or "").strip(),
                bbox_pct=dict(item.get("bbox_pct") or {}),
                meta=dict(item.get("meta") or {}),
            )
        )
    return CrossSheetCandidateIndex(regions_by_sheet=regions_by_sheet)


__all__ = [
    "AnchorRegion",
    "CrossSheetCandidateIndex",
    "build_cross_sheet_index",
]
