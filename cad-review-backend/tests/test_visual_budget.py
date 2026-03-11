from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.contracts import EvidencePackType
from services.audit_runtime.visual_budget import VisualBudget


def test_visual_budget_downgrades_pack_when_global_budget_low():
    budget = VisualBudget(
        image_budget=3_500,
        request_budget=10,
        retry_budget=2,
        priority_reserve_budget=0,
    )

    chosen = budget.request_pack(EvidencePackType.DEEP_PACK, priority="normal")

    assert chosen == EvidencePackType.OVERVIEW_PACK
    assert budget.image_budget == 1_500
    assert budget.request_budget == 9


def test_visual_budget_uses_reserve_budget_for_high_priority_requests():
    budget = VisualBudget(
        image_budget=1_000,
        request_budget=10,
        retry_budget=2,
        priority_reserve_budget=5_000,
    )

    chosen = budget.request_pack(EvidencePackType.FOCUS_PACK, priority="high")

    assert chosen == EvidencePackType.FOCUS_PACK
    assert budget.priority_reserve_budget == 1_000
    assert budget.request_budget == 9


def test_visual_budget_retry_pool_is_consumable():
    budget = VisualBudget(retry_budget=1)

    assert budget.consume_retry() is True
    assert budget.consume_retry() is False


def test_visual_budget_snapshot_keeps_run_mode():
    budget = VisualBudget(run_mode="shadow_legacy")

    assert budget.snapshot()["run_mode"] == "shadow_legacy"
