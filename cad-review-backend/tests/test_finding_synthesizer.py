from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.finding_synthesizer import synthesize_findings
from services.audit_runtime.review_task_schema import WorkerResultCard


def test_finding_synthesizer_merges_worker_cards_into_findings():
    findings, escalations = synthesize_findings(
        worker_results=[
            WorkerResultCard(
                task_id="task-1",
                hypothesis_id="hyp-1",
                worker_kind="elevation_consistency",
                status="confirmed",
                confidence=0.91,
                summary="立面和天花标高不一致",
                evidence=[
                    {
                        "sheet_no": "A3-01",
                        "location": "3.000 标高",
                        "rule_id": "ELEV-001",
                    }
                ],
            )
        ]
    )

    assert len(findings) == 1
    assert findings[0].source_agent == "chief_review_agent"
    assert findings[0].rule_id == "ELEV-001"
    assert escalations == []


def test_finding_synthesizer_escalates_conflicting_worker_cards_to_chief():
    conflict_a = WorkerResultCard(
        task_id="task-a",
        hypothesis_id="hyp-9",
        worker_kind="elevation_consistency",
        status="confirmed",
        confidence=0.88,
        summary="发现问题",
    )
    conflict_b = WorkerResultCard(
        task_id="task-b",
        hypothesis_id="hyp-9",
        worker_kind="elevation_consistency",
        status="rejected",
        confidence=0.82,
        summary="未发现问题",
    )

    findings, escalations = synthesize_findings(worker_results=[conflict_a, conflict_b])

    assert findings == []
    assert escalations[0]["escalate_to_chief"] is True
    assert escalations[0]["hypothesis_id"] == "hyp-9"
