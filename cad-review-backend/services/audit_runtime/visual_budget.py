"""视觉预算控制。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import local

from services.audit_runtime.contracts import EvidencePackType

_ACTIVE_BUDGET = local()


@dataclass
class VisualBudget:
    image_budget: int = 200_000
    request_budget: int = 120
    retry_budget: int = 20
    priority_reserve_budget: int = 40_000

    def request_pack(
        self,
        pack_type: EvidencePackType,
        *,
        priority: str = "normal",
    ) -> EvidencePackType | None:
        normalized_priority = str(priority or "normal").strip().lower()
        pack_cost = self._pack_cost(pack_type)

        if normalized_priority == "high" and self.priority_reserve_budget >= pack_cost:
            self.priority_reserve_budget -= pack_cost
            self.request_budget = max(0, self.request_budget - 1)
            return pack_type

        if self.image_budget >= pack_cost and self.request_budget > 0:
            self.image_budget -= pack_cost
            self.request_budget -= 1
            return pack_type

        downgraded = self._downgrade(pack_type)
        if downgraded is None:
            return None
        return self.request_pack(downgraded, priority=priority)

    def consume_retry(self) -> bool:
        if self.retry_budget <= 0:
            return False
        self.retry_budget -= 1
        return True

    def remaining_retry_budget(self) -> int:
        return max(0, int(self.retry_budget))

    def snapshot(self) -> dict[str, int]:
        return {
            "image_budget": self.image_budget,
            "request_budget": self.request_budget,
            "retry_budget": self.retry_budget,
            "priority_reserve_budget": self.priority_reserve_budget,
        }

    @staticmethod
    def _pack_cost(pack_type: EvidencePackType) -> int:
        costs = {
            EvidencePackType.DEEP_PACK: 8_000,
            EvidencePackType.FOCUS_PACK: 4_000,
            EvidencePackType.PAIRED_OVERVIEW_PACK: 3_000,
            EvidencePackType.OVERVIEW_PACK: 2_000,
        }
        return costs[pack_type]

    @staticmethod
    def _downgrade(pack_type: EvidencePackType) -> EvidencePackType | None:
        if pack_type == EvidencePackType.DEEP_PACK:
            return EvidencePackType.FOCUS_PACK
        if pack_type == EvidencePackType.FOCUS_PACK:
            return EvidencePackType.OVERVIEW_PACK
        if pack_type == EvidencePackType.PAIRED_OVERVIEW_PACK:
            return EvidencePackType.OVERVIEW_PACK
        return None


def set_active_visual_budget(budget: VisualBudget | None) -> None:
    _ACTIVE_BUDGET.current = budget


def get_active_visual_budget() -> VisualBudget | None:
    return getattr(_ACTIVE_BUDGET, "current", None)
