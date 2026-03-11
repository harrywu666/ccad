from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_modules() -> None:
    targets = ("services.feedback_learning_gate",)
    for name in list(sys.modules):
        if name in targets or name.startswith("services.feedback_learning_gate"):
            sys.modules.pop(name, None)


def _load_service():
    _clear_modules()
    return importlib.import_module("services.feedback_learning_gate")


def test_learning_gate_marks_project_specific_case_as_record_only():
    service = _load_service()

    decision = service.evaluate_learning_gate(
        agent_status="resolved_incorrect",
        evidence_score=0.82,
        similar_case_count=0,
        reusability_score=0.2,
    )

    assert decision.learning_decision == "record_only"


def test_learning_gate_accepts_reusable_case():
    service = _load_service()

    decision = service.evaluate_learning_gate(
        agent_status="resolved_incorrect",
        evidence_score=0.88,
        similar_case_count=3,
        reusability_score=0.86,
    )

    assert decision.learning_decision == "accepted_for_learning"


def test_learning_gate_escalates_important_but_uncertain_case():
    service = _load_service()

    decision = service.evaluate_learning_gate(
        agent_status="resolved_incorrect",
        evidence_score=0.61,
        similar_case_count=2,
        reusability_score=0.73,
    )

    assert decision.learning_decision == "needs_human_review"
