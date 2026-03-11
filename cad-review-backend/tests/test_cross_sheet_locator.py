from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_cross_sheet_locator_returns_anchor_pairs_for_elevation_check():
    cross_sheet_index = importlib.import_module("services.audit_runtime.cross_sheet_index")
    cross_sheet_locator = importlib.import_module("services.audit_runtime.cross_sheet_locator")

    index = cross_sheet_index.build_cross_sheet_index(
        sheet_regions=[
            {
                "sheet_no": "A3-01",
                "label": "3.000 标高",
                "bbox_pct": {"x": 0.10, "y": 0.12, "w": 0.08, "h": 0.05},
            },
            {
                "sheet_no": "A2-01",
                "label": "3.000 标高",
                "bbox_pct": {"x": 0.22, "y": 0.18, "w": 0.06, "h": 0.04},
            },
            {
                "sheet_no": "A1-01",
                "label": "3.000 标高",
                "bbox_pct": {"x": 0.31, "y": 0.28, "w": 0.07, "h": 0.05},
            },
        ]
    )

    def _fake_llm_runner(payload):
        assert payload["source_sheet_no"] == "A3-01"
        assert len(payload["candidate_pairs"]) == 2
        return [
            {
                "source_sheet_no": "A3-01",
                "target_sheet_no": "A2-01",
                "source_bbox_pct": {"x": 0.10, "y": 0.12, "w": 0.08, "h": 0.05},
                "target_bbox_pct": {"x": 0.22, "y": 0.18, "w": 0.06, "h": 0.04},
                "confidence": 0.92,
            },
            {
                "source_sheet_no": "A3-01",
                "target_sheet_no": "A1-01",
                "source_bbox_pct": {"x": 0.10, "y": 0.12, "w": 0.08, "h": 0.05},
                "target_bbox_pct": {"x": 0.31, "y": 0.28, "w": 0.07, "h": 0.05},
                "confidence": 0.88,
            },
        ]

    pairs = cross_sheet_locator.locate_across_sheets(
        source_sheet_no="A3-01",
        target_sheet_nos=["A2-01", "A1-01"],
        anchor_hint={"label": "3.000 标高"},
        candidate_index=index,
        llm_runner=_fake_llm_runner,
    )

    assert len(pairs) == 2
    assert pairs[0].target_sheet_no == "A2-01"
    assert pairs[1].target_sheet_no == "A1-01"
