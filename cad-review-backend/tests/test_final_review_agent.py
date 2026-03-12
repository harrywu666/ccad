from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_final_review_rejects_worker_conclusion_without_grounding():
    final_review_agent = importlib.import_module("services.audit_runtime.final_review_agent")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    assignment = review_task_schema.ReviewAssignment(
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
    worker_result = review_task_schema.WorkerResultCard(
        task_id="asg-1",
        hypothesis_id="hyp-1",
        worker_kind="elevation_consistency",
        status="confirmed",
        confidence=0.91,
        summary="标高不一致",
        markdown_conclusion="## 任务结论\n- 标高不一致",
        evidence_bundle={
            "assignment_id": "asg-1",
            "grounding_status": "missing",
            "anchors": [],
            "evidence_pack_id": "paired_overview_pack",
        },
        meta={"assignment_id": "asg-1"},
    )

    decision = final_review_agent.run_final_review_agent(
        assignment=assignment,
        worker_result=worker_result,
    )

    assert decision.decision == "needs_more_evidence"
    assert decision.source_assignment_id == "asg-1"
