from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_dispatch_policy_stops_when_no_workers_pending_no_final_review_pending_and_no_new_directions():
    chief_dispatch_policy = importlib.import_module("services.audit_runtime.chief_dispatch_policy")

    decision = chief_dispatch_policy.evaluate_dispatch_state(
        pending_assignments=[],
        active_worker_count=0,
        final_review_pending_count=0,
        has_new_directions=False,
    )

    assert decision.should_stop is True
    assert decision.should_dispatch is False
    assert decision.should_wait is False


def test_dispatch_policy_dispatches_when_pending_assignments_exist():
    chief_dispatch_policy = importlib.import_module("services.audit_runtime.chief_dispatch_policy")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    decision = chief_dispatch_policy.evaluate_dispatch_state(
        pending_assignments=[
            review_task_schema.ReviewAssignment(
                assignment_id="asg-1",
                review_intent="elevation_consistency",
                source_sheet_no="A1.06",
                target_sheet_nos=["A2.00"],
                task_title="A1.06 -> A2.00",
                acceptance_criteria=["核对标高"],
                expected_evidence_types=["anchors"],
                priority=0.9,
                dispatch_reason="chief_dispatch",
            )
        ],
        active_worker_count=0,
        final_review_pending_count=0,
        has_new_directions=False,
    )

    assert decision.should_dispatch is True
    assert decision.should_stop is False
