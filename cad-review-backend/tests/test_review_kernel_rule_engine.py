from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.context_slicer import build_context_slices
from services.review_kernel.ir_compiler import compile_layout_ir
from services.review_kernel.rule_engine import run_cross_sheet_consistency_rules, run_review_rules


def _build_min_ir(*, sheet_no: str, sheet_title: str) -> dict:
    return {
        "raw_layer": {"document": {"document_id": "doc-1"}},
        "semantic_layer": {
            "logical_sheets": [
                {
                    "logical_sheet_id": "ls-1",
                    "sheet_number": sheet_no,
                    "sheet_title": sheet_title,
                }
            ],
            "review_views": [{"review_view_id": "rv-1"}],
            "references": [],
            "elements": [],
            "tables": [],
        },
        "evidence_layer": {"dimension_evidence": []},
    }


def _build_cross_sheet_ir(
    *,
    sheet_no: str,
    sheet_title: str,
    references: list[dict] | None = None,
    detail_labels: list[str] | None = None,
) -> dict:
    refs = list(references or [])
    labels = list(detail_labels or [])
    return {
        "raw_layer": {
            "document": {"document_id": "doc-1"},
            "raw_entities": {
                "detail_titles": [{"id": f"dt-{idx}", "label": label} for idx, label in enumerate(labels, start=1)],
                "indexes": [],
            },
        },
        "normalized_layer": {
            "normalized_entities": [
                {
                    "id": "ins-1",
                    "source_entity_id": "idx-source-1",
                    "entity_type": "insert",
                    "bbox": [100.0, 100.0, 120.0, 120.0],
                }
            ]
        },
        "semantic_layer": {
            "logical_sheets": [
                {
                    "logical_sheet_id": f"ls-{sheet_no}",
                    "sheet_number": sheet_no,
                    "sheet_title": sheet_title,
                }
            ],
            "review_views": [{"review_view_id": f"rv-{sheet_no}"}],
            "references": refs,
            "elements": [],
            "tables": [],
        },
        "evidence_layer": {"dimension_evidence": []},
    }


def test_rule_engine_detects_broken_reference():
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
    assert "reference_broken" in categories


def test_annotation_missing_skips_document_sheets_but_keeps_plan_sheets():
    doc_ir = _build_min_ir(sheet_no="DL.01", sheet_title="图纸目录")
    doc_issues = run_review_rules(doc_ir, [{"context_slice_id": "cs-doc"}])
    assert "annotation_missing" not in {item["category"] for item in doc_issues}

    plan_ir = _build_min_ir(sheet_no="PL-P1-02", sheet_title="平面布置图")
    plan_issues = run_review_rules(plan_ir, [{"context_slice_id": "cs-plan"}])
    assert "annotation_missing" in {item["category"] for item in plan_issues}


def test_rule_engine_detects_reference_risk_and_material_code_mismatch():
    ir = _build_min_ir(sheet_no="PL-P1-04", sheet_title="完成面定位图")
    ir["semantic_layer"]["references"] = [
        {
            "ref_id": "ref-risk-1",
            "label": "01/T01-PL-01",
            "target_sheet_no": "T01-PL-01",
            "target_missing": False,
            "confidence": 0.52,
            "ambiguity_flags": ["multi_candidate_close_score"],
            "needs_human_confirm": True,
        }
    ]
    ir["semantic_layer"]["elements"] = [
        {"element_id": "el-1", "category": "finish_tag", "material_code": "MR-1001"},
        {"element_id": "el-2", "category": "finish_tag", "material_code": "MR-1002"},
        {"element_id": "el-3", "category": "finish_tag", "material_code": "MR-1003"},
    ]
    ir["semantic_layer"]["tables"] = [
        {
            "table_id": "tb-1",
            "table_type": "material_schedule",
            "rows": [
                {"code": "AB-2001", "name": "木饰面"},
                {"code": "AB-2002", "name": "乳胶漆"},
            ],
        }
    ]

    issues = run_review_rules(ir, [{"context_slice_id": "cs-1"}])
    categories = {item["category"] for item in issues}
    assert "cross_sheet_inconsistency" in categories
    assert "material_mismatch" in categories


def test_cross_sheet_deep_check_detects_missing_target_detail_number():
    source_ir = _build_cross_sheet_ir(
        sheet_no="PL-01",
        sheet_title="平面图",
        references=[
            {
                "ref_id": "ref-1",
                "label": "02/EL-01",
                "source_object_id": "idx-source-1",
                "target_sheet_no": "EL-01",
                "target_missing": False,
                "confidence": 0.83,
            }
        ],
    )
    target_ir = _build_cross_sheet_ir(
        sheet_no="EL-01",
        sheet_title="立面图",
        detail_labels=["01", "03"],
    )

    issues = run_cross_sheet_consistency_rules([source_ir, target_ir])

    assert len(issues) == 1
    issue = issues[0]
    assert issue["rule_id"] == "R-REF-003"
    assert issue["category"] == "cross_sheet_inconsistency"
    assert issue["evidence"]["target_sheet_no"] == "EL-01"
    assert "02" in issue["evidence"]["expected_index_tokens"]


def test_cross_sheet_deep_check_passes_when_target_detail_number_exists():
    source_ir = _build_cross_sheet_ir(
        sheet_no="PL-01",
        sheet_title="平面图",
        references=[
            {
                "ref_id": "ref-1",
                "label": "02/EL-01",
                "source_object_id": "idx-source-1",
                "target_sheet_no": "EL-01",
                "target_missing": False,
                "confidence": 0.83,
            }
        ],
    )
    target_ir = _build_cross_sheet_ir(
        sheet_no="EL-01",
        sheet_title="立面图",
        detail_labels=["02", "03"],
    )

    issues = run_cross_sheet_consistency_rules([source_ir, target_ir])

    assert issues == []
