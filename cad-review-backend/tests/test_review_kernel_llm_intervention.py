from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.llm_intervention import disambiguate_reference_bindings  # noqa: E402


def _build_ir() -> dict:
    cand1 = {
        "candidate_id": "cand-1",
        "sheet_no": "A4.01",
        "score": 0.81,
        "is_known_sheet": True,
        "basis": ["token_exact"],
    }
    cand2 = {
        "candidate_id": "cand-2",
        "sheet_no": "A4.02",
        "score": 0.8,
        "is_known_sheet": True,
        "basis": ["token_partial"],
    }
    return {
        "semantic_layer": {
            "references": [
                {
                    "ref_id": "ref-1",
                    "target_sheet_no": "A4.01",
                    "selected_candidate_id": "cand-1",
                    "target_missing": False,
                    "confidence": 0.81,
                    "candidate_bindings": [cand1, cand2],
                    "needs_llm_disambiguation": True,
                    "ambiguity_flags": ["multi_candidate_close_score"],
                }
            ],
            "candidate_relations": [
                {
                    "relation_id": "ref-1",
                    "raw_label": "A1/A4.01",
                    "candidate_bindings": [cand1, cand2],
                    "selected_candidate_id": "cand-1",
                    "needs_llm_disambiguation": True,
                    "ambiguity_flags": ["multi_candidate_close_score"],
                    "confidence": 0.81,
                }
            ],
        }
    }


def _build_slice(ir_package: dict) -> dict:
    return {
        "context_slice_id": "cs-1",
        "slice_type": "relation_disambiguation",
        "payload": {
            "logical_sheet": {"logical_sheet_id": "ls-1", "sheet_number": "A1.01"},
            "review_view": {"review_view_id": "rv-1"},
            "candidate_relations": ir_package["semantic_layer"]["candidate_relations"],
            "dimension_evidence": [
                {
                    "display_value": 1000,
                    "measured_value": 998,
                    "computed_value": 998,
                    "confidence": 0.9,
                }
            ],
            "degradation_notices": [],
        },
    }


def test_disambiguation_program_first_without_llm(monkeypatch):
    monkeypatch.delenv("REVIEW_KERNEL_LLM_ENABLED", raising=False)
    ir_package = _build_ir()
    trace = disambiguate_reference_bindings(ir_package, _build_slice(ir_package))
    assert trace["llm_used"] is False
    assert ir_package["semantic_layer"]["references"][0]["selected_candidate_id"] == "cand-1"
    assert ir_package["semantic_layer"]["references"][0]["target_sheet_no"] == "A4.01"


def test_disambiguation_allows_llm_to_select_existing_candidate(monkeypatch):
    monkeypatch.setenv("REVIEW_KERNEL_LLM_ENABLED", "1")
    monkeypatch.setenv("REVIEW_KERNEL_LLM_DISAMBIGUATION_ENABLED", "1")
    ir_package = _build_ir()

    def fake_llm(_system_prompt: str, _user_prompt: str, _max_tokens: int):
        return [
            {
                "relation_id": "ref-1",
                "candidate_id": "cand-2",
                "confidence": 0.82,
                "reason": "target_sheet更贴近节点语义",
            }
        ]

    trace = disambiguate_reference_bindings(
        ir_package,
        _build_slice(ir_package),
        llm_call=fake_llm,
    )
    assert trace["llm_used"] is True
    assert ir_package["semantic_layer"]["references"][0]["selected_candidate_id"] == "cand-2"
    assert ir_package["semantic_layer"]["references"][0]["target_sheet_no"] == "A4.02"
