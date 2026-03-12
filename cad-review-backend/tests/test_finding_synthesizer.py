from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.finding_synthesizer import synthesize_findings
from services.audit_runtime.review_task_schema import WorkerResultCard


def test_finding_synthesizer_promotes_confirmed_worker_cards_to_findings():
    findings, escalations = synthesize_findings(
        worker_results=[
            WorkerResultCard(
                task_id="task-1",
                hypothesis_id="hyp-1",
                worker_kind="material_semantic_consistency",
                status="confirmed",
                confidence=0.91,
                summary="材料命名冲突",
                evidence=[
                    {
                        "sheet_no": "A1.01",
                        "location": "材料表 M-01",
                        "rule_id": "MAT-001",
                        "evidence_pack_id": "focus_pack",
                    }
                ],
                meta={"severity": "warning"},
            )
        ]
    )

    assert escalations == []
    assert len(findings) == 1
    assert findings[0].source_agent == "chief_review_agent"
    assert findings[0].meta["execution_mode"] == "worker_result"


def test_finding_synthesizer_escalates_conflicting_worker_cards_to_chief():
    conflict_a = WorkerResultCard(
        task_id="task-a",
        hypothesis_id="hyp-2",
        worker_kind="index_reference",
        status="confirmed",
        confidence=0.88,
        summary="索引成立",
    )
    conflict_b = WorkerResultCard(
        task_id="task-b",
        hypothesis_id="hyp-2",
        worker_kind="index_reference",
        status="rejected",
        confidence=0.76,
        summary="索引不成立",
    )

    findings, escalations = synthesize_findings(worker_results=[conflict_a, conflict_b])

    assert findings == []
    assert escalations[0]["escalate_to_chief"] is True
    assert escalations[0]["hypothesis_id"] == conflict_a.hypothesis_id


def test_finding_synthesizer_resolves_high_confidence_majority_conflict():
    findings, escalations = synthesize_findings(
        worker_results=[
            WorkerResultCard(
                task_id="task-a",
                hypothesis_id="hyp-3",
                worker_kind="index_reference",
                status="confirmed",
                confidence=0.93,
                summary="索引引用成立",
                meta={"severity": "warning"},
            ),
            WorkerResultCard(
                task_id="task-b",
                hypothesis_id="hyp-3",
                worker_kind="index_reference",
                status="confirmed",
                confidence=0.88,
                summary="索引与目标图号一致",
                meta={"severity": "warning"},
            ),
            WorkerResultCard(
                task_id="task-c",
                hypothesis_id="hyp-3",
                worker_kind="index_reference",
                status="rejected",
                confidence=0.51,
                summary="局部证据不足",
            ),
        ]
    )

    assert escalations == []
    assert len(findings) == 1
    assert findings[0].triggered_by == "hyp-3"


def test_finding_synthesizer_preserves_worker_skill_metadata():
    findings, escalations = synthesize_findings(
        worker_results=[
            WorkerResultCard(
                task_id="task-skill",
                hypothesis_id="hyp-skill",
                worker_kind="index_reference",
                status="confirmed",
                confidence=0.9,
                summary="索引引用成立",
                meta={
                    "severity": "warning",
                    "skill_mode": "worker_skill",
                    "skill_id": "index_reference",
                    "skill_path": "/tmp/index_reference/SKILL.md",
                },
            )
        ]
    )

    assert escalations == []
    assert findings[0].meta["execution_mode"] == "worker_skill"
    assert findings[0].meta["skill_id"] == "index_reference"
