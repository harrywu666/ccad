"""共享可疑图注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from domain.sheet_normalization import normalize_sheet_no


@dataclass(frozen=True)
class HotSheetSignal:
    sheet_no: str
    sheet_key: str
    finding_type: str
    confidence: float
    source_agent: str
    score: float


class HotSheetRegistry:
    """只共享可疑图优先级，不承载通用消息。"""

    def __init__(self) -> None:
        self._signals: List[HotSheetSignal] = []

    def publish(
        self,
        sheet_no: str | None,
        *,
        finding_type: str,
        confidence: float,
        source_agent: str,
    ) -> None:
        sheet_text = str(sheet_no or "").strip()
        sheet_key = normalize_sheet_no(sheet_text)
        if not sheet_key:
            return
        normalized_confidence = max(0.0, min(1.0, float(confidence or 0.0)))
        self._signals.append(
            HotSheetSignal(
                sheet_no=sheet_text or sheet_key,
                sheet_key=sheet_key,
                finding_type=str(finding_type or "unknown").strip() or "unknown",
                confidence=normalized_confidence,
                source_agent=str(source_agent or "unknown_agent").strip() or "unknown_agent",
                score=round(normalized_confidence + 0.15, 3),
            )
        )

    def score(self, sheet_no: str | None) -> float:
        sheet_key = normalize_sheet_no(sheet_no or "")
        if not sheet_key:
            return 0.0
        matches = [signal.score for signal in self._signals if signal.sheet_key == sheet_key]
        if not matches:
            return 0.0
        return round(max(matches) + max(0, len(matches) - 1) * 0.05, 3)

    def get_hot_sheets(self) -> List[HotSheetSignal]:
        ranked: dict[str, HotSheetSignal] = {}
        for signal in self._signals:
            current = ranked.get(signal.sheet_key)
            if current is None or signal.score > current.score:
                ranked[signal.sheet_key] = signal
        return sorted(ranked.values(), key=lambda item: (-item.score, item.sheet_no))

    def sort_sheet_items(
        self,
        items: Iterable[object],
        sheet_no_getter,
    ) -> List[object]:
        return sorted(
            list(items),
            key=lambda item: (-self.score(sheet_no_getter(item)), str(sheet_no_getter(item) or "")),
        )
