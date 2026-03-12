from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.review_task_schema import ReviewAssignment


def test_review_assignment_rejects_empty_targets():
    with pytest.raises(ValidationError):
        ReviewAssignment(
            assignment_id="asg-1",
            review_intent="elevation_consistency",
            source_sheet_no="A1.06",
            target_sheet_nos=[],
            task_title="A1.06 -> ?",
            acceptance_criteria=["核对标高文字"],
            expected_evidence_types=["anchors"],
            priority=0.9,
            dispatch_reason="chief_dispatch",
        )


def test_review_assignment_rejects_more_than_two_targets():
    with pytest.raises(ValidationError):
        ReviewAssignment(
            assignment_id="asg-1",
            review_intent="elevation_consistency",
            source_sheet_no="A1.06",
            target_sheet_nos=["A2.00", "A2.01", "A2.02"],
            task_title="A1.06 -> A2.*",
            acceptance_criteria=["核对标高文字"],
            expected_evidence_types=["anchors"],
            priority=0.9,
            dispatch_reason="chief_dispatch",
        )


@pytest.mark.parametrize("targets", [["A2.00"], ["A2.00", "A2.01"]])
def test_review_assignment_accepts_one_or_two_targets(targets: list[str]):
    assignment = ReviewAssignment(
        assignment_id="asg-1",
        review_intent="elevation_consistency",
        source_sheet_no="A1.06",
        target_sheet_nos=targets,
        task_title="A1.06 -> A2.*",
        acceptance_criteria=["核对标高文字"],
        expected_evidence_types=["anchors"],
        priority=0.9,
        dispatch_reason="chief_dispatch",
    )

    assert assignment.target_sheet_nos == targets
