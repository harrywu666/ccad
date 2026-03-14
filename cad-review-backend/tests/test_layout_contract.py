from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.layout_contract import ensure_layout_json_contract


def test_layout_contract_upgrades_legacy_payload():
    payload = {
        "source_dwg": "A1.01 平面图.dwg",
        "layout_name": "A1.01 平面图",
        "sheet_no": "A1.01",
        "sheet_name": "平面布置图",
        "dimensions": [{"id": "D1", "value": 1200}],
        "indexes": [],
        "materials": [],
    }

    upgraded, changed, fields = ensure_layout_json_contract(payload)

    assert changed is True
    assert "schema_version" in fields
    assert upgraded["schema_version"] == "1.2.0"
    assert upgraded["schema_name"] == "dwg_layout_semantic_payload"
    assert isinstance(upgraded["viewports"], list)
    assert isinstance(upgraded["layer_state_snapshot"], dict)
    assert isinstance(upgraded["text_encoding_evidence"], list)
    assert isinstance(upgraded["z_range_summary"], dict)
    assert isinstance(upgraded["drawing_register_entry"], dict)
    assert isinstance(upgraded["insert_entities"], list)


def test_layout_contract_keeps_existing_extended_fields():
    payload = {
        "schema_name": "dwg_layout_semantic_payload",
        "schema_version": "1.2.0",
        "source_dwg": "A1.01 平面图.dwg",
        "layout_name": "A1.01 平面图",
        "sheet_no": "A1.01",
        "sheet_name": "平面布置图",
        "viewports": [],
        "dimensions": [],
        "pseudo_texts": [],
        "indexes": [],
        "title_blocks": [],
        "detail_titles": [],
        "materials": [],
        "material_table": [],
        "layers": [],
        "layout_frames": [],
        "layout_fragments": [],
        "insert_entities": [],
        "is_multi_sheet_layout": False,
        "scale": "",
        "model_range": {"min": [0.0, 0.0], "max": [0.0, 0.0]},
        "layout_page_range": {"min": [0.0, 0.0], "max": [0.0, 0.0]},
        "layer_state_snapshot": {"layer_visibility": []},
        "text_encoding_evidence": [],
        "z_range_summary": {"z_min": 0.0, "z_max": 0.0, "ambiguous_count": 0, "sample_count": 0},
        "drawing_register_entry": {"sheet_number": "A1.01", "title": "平面布置图", "layout_name": "A1.01 平面图"},
    }

    upgraded, changed, fields = ensure_layout_json_contract(payload)

    assert changed is False
    assert fields == []
    assert upgraded["schema_version"] == "1.2.0"
