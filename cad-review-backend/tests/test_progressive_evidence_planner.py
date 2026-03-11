from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.contracts import EvidencePackType
from services.audit_runtime.evidence_planner import next_pack_type, plan_deep, plan_lite


def test_plan_lite_prefers_paired_overview_for_relationship():
    plans = plan_lite(
        task_type="relationship",
        source_sheet_no="A1.01",
        target_sheet_no="A4.01",
    )

    assert len(plans) == 1
    assert plans[0].pack_type.value == "paired_overview_pack"
    assert plans[0].round_index == 1


def test_plan_lite_does_not_default_to_deep_pack_for_relationship():
    plans = plan_lite(
        task_type="relationship",
        source_sheet_no="A1.01",
        target_sheet_no="A4.01",
    )

    assert plans[0].pack_type.value != "deep_pack"


def test_plan_deep_escalates_from_paired_overview_to_focus():
    plans = plan_deep(
        task_type="relationship",
        source_sheet_no="A1.01",
        target_sheet_no="A4.01",
        current_pack_type=EvidencePackType.PAIRED_OVERVIEW_PACK,
        current_round=1,
        triggered_by="confidence_low",
    )

    assert len(plans) == 1
    assert plans[0].pack_type.value == "focus_pack"
    assert plans[0].round_index == 2
    assert plans[0].meta["triggered_by"] == "confidence_low"


def test_plan_deep_stops_after_second_round():
    plans = plan_deep(
        task_type="relationship",
        source_sheet_no="A1.01",
        target_sheet_no="A4.01",
        current_pack_type=EvidencePackType.FOCUS_PACK,
        current_round=2,
        triggered_by="confidence_low",
    )

    assert plans == []


def test_next_pack_type_promotes_to_deeper_pack():
    assert next_pack_type(EvidencePackType.OVERVIEW_PACK).value == "focus_pack"
    assert next_pack_type(EvidencePackType.PAIRED_OVERVIEW_PACK).value == "focus_pack"
    assert next_pack_type(EvidencePackType.FOCUS_PACK).value == "deep_pack"
