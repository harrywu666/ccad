from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.ir_compiler import compile_layout_ir


def test_compile_layout_ir_builds_four_layers_and_dimension_evidence():
    payload = {
        "source_dwg": "A1.01 平面图.dwg",
        "layout_name": "A1.01 平面图",
        "sheet_no": "A1.01",
        "sheet_name": "平面布置图",
        "layout_page_range": {"min": [0, 0], "max": [841, 594]},
        "dimensions": [
            {
                "id": "D-1",
                "value": 1000,
                "display_text": "1000",
                "source": "paper_space",
                "text_position": [120, 90],
            }
        ],
        "indexes": [
            {
                "id": "IDX-1",
                "index_no": "A1",
                "target_sheet": "A4.02",
            }
        ],
    }

    ir = compile_layout_ir(
        payload,
        source_json_path="/tmp/a101.json",
        known_sheet_nos={"A1.01"},
    )

    assert ir["schema_name"] == "dwg_to_json_core"
    assert ir["schema_version"] == "1.2.0"
    assert "raw_layer" in ir
    assert "normalized_layer" in ir
    assert "semantic_layer" in ir
    assert "evidence_layer" in ir

    dimensions = ir["evidence_layer"]["dimension_evidence"]
    assert len(dimensions) == 1
    assert dimensions[0]["display_value"] == 1000
    assert dimensions[0]["truth_role"] == "display_value_authoritative"
    assert dimensions[0]["value_source"] == "display_preferred"

    refs = ir["semantic_layer"]["references"]
    assert len(refs) == 1
    assert refs[0]["target_missing"] is True
    assert isinstance(refs[0]["candidate_bindings"], list)
    assert len(ir["semantic_layer"]["candidate_relations"]) == 1


def test_compile_layout_ir_prefers_global_pct_for_dimension_bbox():
    payload = {
        "source_dwg": "A1.01 平面图.dwg",
        "layout_name": "A1.01 平面图",
        "sheet_no": "A1.01",
        "sheet_name": "平面布置图",
        "layout_page_range": {"min": [0, 0], "max": [1000, 1000]},
        "dimensions": [
            {
                "id": "D-1",
                "value": 1000,
                "display_text": "1000",
                "source": "model_space",
                "text_position": [9000, 9000],
                "global_pct": {"x": 20.0, "y": 30.0},
            }
        ],
    }

    ir = compile_layout_ir(
        payload,
        source_json_path="/tmp/a101_pct.json",
    )
    dim = ir["evidence_layer"]["dimension_evidence"][0]
    bbox = dim["bbox_canonical"]
    center_x = (float(bbox[0]) + float(bbox[2])) / 2.0
    center_y = (float(bbox[1]) + float(bbox[3])) / 2.0

    assert round(center_x, 1) == 200.0
    assert round(center_y, 1) == 700.0
    assert dim["location_basis"] == "global_pct_projection"


def test_compile_layout_ir_prefers_global_pct_for_text_and_insert_bbox():
    payload = {
        "source_dwg": "A1.01 平面图.dwg",
        "layout_name": "A1.01 平面图",
        "sheet_no": "A1.01",
        "sheet_name": "平面布置图",
        "layout_page_range": {"min": [0, 0], "max": [1000, 1000]},
        "dimensions": [],
        "pseudo_texts": [
            {
                "id": "T-1",
                "content": "FFL 0",
                "source": "model_space",
                "position": [8000, 8000],
                "global_pct": {"x": 60.0, "y": 40.0},
            }
        ],
        "insert_entities": [
            {
                "id": "I-1",
                "source": "model_space",
                "block_name": "DOOR-A",
                "position": [7000, 7000],
                "global_pct": {"x": 70.0, "y": 20.0},
                "effective_geometry": {"bbox": [6900, 6900, 7100, 7100], "resolved": True},
            }
        ],
    }

    ir = compile_layout_ir(
        payload,
        source_json_path="/tmp/a101_pct_text_insert.json",
    )
    entities = ir["normalized_layer"]["normalized_entities"]
    text_entity = next(item for item in entities if item["entity_type"] == "text")
    insert_entity = next(item for item in entities if item["entity_type"] == "insert")

    text_bbox = text_entity["bbox"]
    text_center = (
        (float(text_bbox[0]) + float(text_bbox[2])) / 2.0,
        (float(text_bbox[1]) + float(text_bbox[3])) / 2.0,
    )
    assert round(text_center[0], 1) == 600.0
    assert round(text_center[1], 1) == 600.0
    assert text_entity["location_basis"] == "global_pct_projection"

    insert_bbox = insert_entity["bbox"]
    insert_center = (
        (float(insert_bbox[0]) + float(insert_bbox[2])) / 2.0,
        (float(insert_bbox[1]) + float(insert_bbox[3])) / 2.0,
    )
    assert round(insert_center[0], 1) == 700.0
    assert round(insert_center[1], 1) == 800.0
    assert insert_entity["location_basis"] == "global_pct_projection"
