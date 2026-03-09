from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.evidence_planner import plan_evidence_requests


def test_relationship_task_prefers_paired_overview_pack():
    plans = plan_evidence_requests(
        task_type="relationship",
        source_sheet_no="A1.01",
        target_sheet_no="A4.03",
    )

    assert len(plans) == 1
    assert plans[0].pack_type.value == "paired_overview_pack"
    assert plans[0].source_sheet_no == "A1.01"
    assert plans[0].target_sheet_no == "A4.03"


def test_dimension_task_prefers_structured_first():
    plans = plan_evidence_requests(
        task_type="dimension",
        source_sheet_no="A2.01",
        requires_visual=False,
    )

    assert plans == []


def test_material_task_avoids_deep_pack_by_default():
    plans = plan_evidence_requests(
        task_type="material",
        source_sheet_no="A5.01",
    )

    assert len(plans) == 1
    assert plans[0].pack_type.value == "focus_pack"


def test_evidence_plan_item_is_serializable():
    plan = plan_evidence_requests(
        task_type="relationship",
        source_sheet_no="A1.01",
        target_sheet_no="A4.03",
    )[0]

    payload = plan.to_dict()

    assert payload["task_type"] == "relationship"
    assert payload["pack_type"] == "paired_overview_pack"
    assert payload["source_sheet_no"] == "A1.01"
    assert payload["target_sheet_no"] == "A4.03"
    assert payload["round_index"] == 1
    assert isinstance(payload["reason"], str) and payload["reason"]
