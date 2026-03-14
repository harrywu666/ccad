from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.issue_policy import (  # noqa: E402
    apply_confidence_propagation,
    enforce_high_severity_constraint,
)


def test_confidence_propagation_respects_weakest_evidence():
    issues = [
        {
            "issue_id": "iss-1",
            "confidence": 0.95,
            "severity": "error",
            "generated_by": "rule_engine",
            "evidence": {"dimension_evidence_id": "dim-1"},
        }
    ]
    ir_package = {
        "evidence_layer": {
            "dimension_evidence": [{"dimension_id": "dim-1", "confidence": 0.61}],
            "degradation_notices": [{"severity": "medium"}],
        }
    }
    patched = apply_confidence_propagation(issues, ir_package)
    assert patched[0]["confidence"] == 0.61


def test_high_severity_constraint_downgrades_free_form_llm_issue():
    issues = [
        {
            "issue_id": "iss-2",
            "severity": "error",
            "generated_by": "llm",
            "rule_id": "",
            "evidence": {},
            "reviewed_status": "open",
        }
    ]
    patched = enforce_high_severity_constraint(issues)
    assert patched[0]["severity"] == "warning"
    assert patched[0]["reviewed_status"] == "needs_human_review"
