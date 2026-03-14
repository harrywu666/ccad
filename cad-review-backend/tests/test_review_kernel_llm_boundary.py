from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.llm_boundary import (  # noqa: E402
    LLM_STAGE_DISAMBIGUATION,
    check_llm_boundary,
)


def _valid_slice() -> dict:
    return {
        "context_slice_id": "cs-1",
        "slice_type": "relation_disambiguation",
        "payload": {
            "logical_sheet": {"logical_sheet_id": "ls-1", "sheet_number": "A1.01"},
            "review_view": {"review_view_id": "rv-1"},
            "candidate_relations": [{"relation_id": "ref-1", "candidate_bindings": [{"candidate_id": "c1"}]}],
            "dimension_evidence": [
                {
                    "display_value": 1000,
                    "measured_value": 998,
                    "computed_value": 998,
                }
            ],
        },
    }


def test_llm_boundary_allows_disambiguation_when_structure_ready():
    decision = check_llm_boundary(stage=LLM_STAGE_DISAMBIGUATION, context_slice=_valid_slice())
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_llm_boundary_rejects_raw_dump_payload():
    context_slice = _valid_slice()
    context_slice["payload"]["raw_layer"] = {"raw_entities": []}
    decision = check_llm_boundary(stage=LLM_STAGE_DISAMBIGUATION, context_slice=context_slice)
    assert decision.allowed is False
    assert decision.reason == "raw_dump_forbidden"


def test_llm_boundary_rejects_missing_candidates():
    context_slice = _valid_slice()
    context_slice["payload"]["candidate_relations"] = []
    decision = check_llm_boundary(stage=LLM_STAGE_DISAMBIGUATION, context_slice=context_slice)
    assert decision.allowed is False
    assert decision.reason == "candidate_relations_missing"
