from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_chief_review_session_generates_worker_task_cards():
    chief_review_session = importlib.import_module("services.audit_runtime.chief_review_session")

    session = chief_review_session.ChiefReviewSession(
        project_id="proj-chief",
        audit_version=1,
    )
    cards = session.plan_worker_tasks(
        memory={
            "active_hypotheses": [
                {
                    "id": "hyp-1",
                    "topic": "标高一致性",
                    "objective": "核对立面与天花图中的 3.000 标高",
                    "source_sheet_no": "A3-01",
                    "target_sheet_nos": ["A2-01", "A1-01"],
                }
            ]
        }
    )

    assert cards[0].worker_kind == "elevation_consistency"
    assert cards[0].source_sheet_no == "A3-01"
    assert cards[0].target_sheet_nos == ["A2-01", "A1-01"]


def test_chief_review_session_marks_skillized_worker_context():
    chief_review_session = importlib.import_module("services.audit_runtime.chief_review_session")

    session = chief_review_session.ChiefReviewSession(
        project_id="proj-chief",
        audit_version=2,
    )
    cards = session.plan_worker_tasks(
        memory={
            "active_hypotheses": [
                {
                    "id": "hyp-2",
                    "topic": "材料一致性",
                    "objective": "核对材料表和材料标注",
                    "source_sheet_no": "A1-01",
                    "target_sheet_nos": [],
                }
            ]
        }
    )

    assert cards[0].worker_kind == "material_semantic_consistency"
    assert cards[0].context["execution_mode"] == "worker_skill"
    assert cards[0].context["skill_id"] == "material_semantic_consistency"


def test_chief_review_session_marks_dimension_skillized_worker_context():
    chief_review_session = importlib.import_module("services.audit_runtime.chief_review_session")

    session = chief_review_session.ChiefReviewSession(
        project_id="proj-chief",
        audit_version=3,
    )
    cards = session.plan_worker_tasks(
        memory={
            "active_hypotheses": [
                {
                    "id": "hyp-3",
                    "topic": "标高一致性",
                    "objective": "核对两张图里的 3.000 标高",
                    "source_sheet_no": "A1-01",
                    "target_sheet_nos": ["A3-01"],
                }
            ]
        }
    )

    assert cards[0].worker_kind == "elevation_consistency"
    assert cards[0].context["execution_mode"] == "worker_skill"
    assert cards[0].context["skill_id"] == "elevation_consistency"
