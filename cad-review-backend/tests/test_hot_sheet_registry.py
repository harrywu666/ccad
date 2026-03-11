from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.hot_sheet_registry import HotSheetRegistry


def test_hot_sheet_registry_ranks_sheets_by_confidence():
    registry = HotSheetRegistry()
    registry.publish("A4.03", finding_type="broken_ref", confidence=0.32, source_agent="relationship_review_agent")
    registry.publish("A1.01", finding_type="dim_mismatch", confidence=0.88, source_agent="dimension_review_agent")

    hot = registry.get_hot_sheets()

    assert hot[0].sheet_no == "A1.01"
    assert hot[1].sheet_no == "A4.03"


def test_hot_sheet_registry_only_changes_priority_not_payload():
    registry = HotSheetRegistry()
    sheets = [
        {"sheet_no": "A4.03", "payload": "x"},
        {"sheet_no": "A1.01", "payload": "y"},
    ]
    registry.publish("A4.03", finding_type="broken_ref", confidence=0.91, source_agent="relationship_review_agent")

    ordered = registry.sort_sheet_items(sheets, lambda item: item["sheet_no"])

    assert [item["sheet_no"] for item in ordered] == ["A4.03", "A1.01"]
    assert ordered[0]["payload"] == "x"
