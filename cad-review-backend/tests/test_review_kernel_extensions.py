from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.context_slicer import build_context_slices
from services.review_kernel.ir_compiler import compile_layout_ir


def _sample_payload() -> dict:
    return {
        "source_dwg": "A1.01 平面图.dwg",
        "layout_name": "A1.01 平面图",
        "sheet_no": "A1.01",
        "sheet_name": "平面布置图",
        "layout_page_range": {"min": [0, 0], "max": [841, 594]},
        "dimensions": [
            {
                "id": "DIM-1",
                "value": 900,
                "display_text": "1000",
                "source": "model_space",
                "text_position": [120, 90],
                "z_min": 0.0,
                "z_max": 0.0,
                "z_range_label": "dimension_annotation",
                "elevation_band": "human_accessible",
                "z_ambiguous": True,
            }
        ],
        "indexes": [
            {
                "id": "IDX-1",
                "index_no": "A1",
                "target_sheet": "A4.02",
            }
        ],
        "pseudo_texts": [
            {
                "id": "TXT-FFL",
                "content": "FFL 0",
                "position": [30, 20],
                "source": "model_space",
                "encoding": {
                    "raw_bytes_hex": "46464C2030",
                    "encoding_detected": "UTF-8",
                    "encoding_confidence": 0.97,
                    "text_utf8": "FFL 0",
                    "font_name": "hztxt.shx",
                    "font_substitution": "Noto Sans CJK SC",
                    "font_substitution_reason": "shx_not_renderable",
                    "ocr_fallback": None,
                    "ocr_triggered": False,
                },
                "z_min": 0.0,
                "z_max": 0.0,
                "z_range_label": "annotation_text",
                "elevation_band": "human_accessible",
                "z_ambiguous": True,
            },
            {
                "id": "TXT-FCL",
                "content": "FCL 2600",
                "position": [60, 20],
                "source": "model_space",
                "encoding": {
                    "raw_bytes_hex": "46434C2032363030",
                    "encoding_detected": "UTF-8",
                    "encoding_confidence": 0.97,
                    "text_utf8": "FCL 2600",
                    "font_name": "hztxt.shx",
                    "font_substitution": "Noto Sans CJK SC",
                    "font_substitution_reason": "shx_not_renderable",
                    "ocr_fallback": None,
                    "ocr_triggered": False,
                },
                "z_min": 0.0,
                "z_max": 0.0,
                "z_range_label": "annotation_text",
                "elevation_band": "human_accessible",
                "z_ambiguous": True,
            },
        ],
        "insert_entities": [
            {
                "id": "INS-1",
                "block_name": "*U12",
                "source": "model_space",
                "layer": "A-DOOR",
                "position": [100, 100],
                "z_min": 0.0,
                "z_max": 0.0,
                "z_range_label": "door",
                "elevation_band": "human_accessible",
                "z_ambiguous": True,
                "included_in_plan_extraction": True,
                "inferred_type": "door",
                "inferred_type_confidence": 0.92,
                "is_dynamic_block": True,
                "dynamic_params": {"width_stretch_mm": 900},
                "effective_geometry": {
                    "resolved": False,
                    "bbox": [95, 95, 115, 115],
                    "degraded_reason": "dynamic_block_not_resolved",
                    "fallback_geometry": "block_definition_default",
                    "impacted_attributes": ["width_mm", "rotation_effective"],
                },
                "dynamic_resolution_source": "degraded_default_geometry",
                "attributes": {
                    "WIDTH": {"raw_value": "900", "semantic_role": "door_width", "numeric_value": 900, "unit": "mm"}
                },
            }
        ],
        "layers": [{"name": "A-DOOR", "visible": True, "on": True, "frozen": False, "locked": False}],
        "viewports": [
            {
                "id": "VP-01",
                "viewport_id": 2,
                "model_range": {"min": [0, 0], "max": [12000, 8000]},
                "layer_overrides": [{"layer_name": "A-CLNG", "visible": False, "override_type": "vp_freeze"}],
                "clip_boundary": {
                    "enabled": True,
                    "clip_type": "polygonal",
                    "boundary_polygon": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                    "source_entity_id": "E-CLIP-01",
                },
            }
        ],
        "layout_fragments": [{"fragment_id": "frag-1", "sheet_name": "平面布置图", "fragment_bbox": {"min": [0, 0], "max": [841, 594]}}],
        "layer_state_snapshot": {
            "layer_state_id": "LST-1",
            "owner_layout_name": "A1.01 平面图",
            "name": "A1.01_STATE",
            "layer_visibility": [{"layer_name": "A-DOOR", "visible": True}],
            "viewport_overrides": [{"viewport_id": "VP-01", "layer_name": "A-CLNG", "visible": False, "override_type": "vp_freeze"}],
            "source": "viewport_overrides",
            "confidence": 0.95,
        },
        "z_range_summary": {"z_min": 0.0, "z_max": 2600.0, "ambiguous_count": 3, "sample_count": 4},
        "text_encoding_evidence": [
            {
                "source_entity_id": "TXT-FFL",
                "encoding_detected": "UTF-8",
                "encoding_confidence": 0.97,
                "font_name": "hztxt.shx",
                "font_substitution": "Noto Sans CJK SC",
                "font_substitution_reason": "shx_not_renderable",
                "ocr_triggered": False,
                "ocr_fallback": None,
            }
        ],
    }


def test_compile_layout_ir_contains_extension_structures():
    ir = compile_layout_ir(
        _sample_payload(),
        source_json_path="/tmp/a101.ext.json",
        known_sheet_nos={"A1.01", "A4.02"},
        project_id="proj-ext-1",
        project_name="扩展测试项目",
        drawing_register_entries=[{"sheet_number": "A1.01", "title": "平面布置图", "sheet_type": "floor_plan"}],
    )

    assert ir["project"]["project_id"] == "proj-ext-1"
    assert len(ir["drawing_register"]["entries"]) >= 1
    assert ir["company_parsing_profile"]["company_profile_id"]
    assert ir["normalized_layer"]["tolerance_registry"]["dimension_value_mm"] == 1.0
    assert ir["normalized_layer"]["layer_state_snapshots"]
    assert ir["semantic_layer"]["block_semantic_profiles"]
    assert ir["semantic_layer"]["clear_height_chains"]
    assert "encoding_evidence" in ir["evidence_layer"]
    assert "sanitization_logs" in ir["evidence_layer"]
    reasons = {str(item.get("reason") or "") for item in ir["evidence_layer"]["degradation_notices"]}
    assert "dynamic_block_not_resolved" in reasons
    assert "z_axis_ambiguous" in reasons


def test_context_slices_keep_extension_payloads_without_raw_layer():
    ir = compile_layout_ir(
        _sample_payload(),
        source_json_path="/tmp/a101.ext.slice.json",
        known_sheet_nos={"A1.01", "A4.02"},
    )
    slices = build_context_slices(ir, max_slice_tokens=2200)
    by_type = {str(item.get("slice_type") or ""): item for item in slices}

    space_payload = by_type["space_review"]["payload"]
    relation_payload = by_type["relation_disambiguation"]["payload"]
    assert "clear_height_chains" in space_payload
    assert "block_semantic_profiles" in space_payload
    assert "encoding_evidence" in relation_payload
    assert "dimension_evidence" in relation_payload
    assert "raw_layer" not in relation_payload
