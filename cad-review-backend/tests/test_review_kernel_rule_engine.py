from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.context_slicer import build_context_slices
from services.review_kernel.ir_compiler import compile_layout_ir
from services.review_kernel.rule_engine import run_review_rules


def test_rule_engine_detects_dimension_conflict_and_broken_reference():
    payload = {
        "source_dwg": "A1.02 地坪图.dwg",
        "layout_name": "A1.02 地坪图",
        "sheet_no": "A1.02",
        "sheet_name": "地坪布置图",
        "layout_page_range": {"min": [0, 0], "max": [841, 594]},
        "dimensions": [
            {
                "id": "DIM-99",
                "value": 750,
                "display_text": "900",
                "source": "model_space",
                "text_position": [220, 300],
            }
        ],
        "indexes": [
            {
                "id": "IDX-99",
                "index_no": "B3",
                "target_sheet": "A9.99",
            }
        ],
    }

    ir = compile_layout_ir(
        payload,
        source_json_path="/tmp/a102.json",
        known_sheet_nos={"A1.02"},
    )
    slices = build_context_slices(ir, max_slice_tokens=1200)
    issues = run_review_rules(ir, slices)

    categories = {item["category"] for item in issues}
    assert "dimension_conflict" in categories
    assert "reference_broken" in categories
