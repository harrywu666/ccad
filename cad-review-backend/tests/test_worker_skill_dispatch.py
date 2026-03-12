from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_chief_session_marks_skillized_worker_tasks():
    chief_review_session = importlib.import_module("services.audit_runtime.chief_review_session")

    session = chief_review_session.ChiefReviewSession(project_id="proj-chief", audit_version=1)
    tasks = session.plan_worker_tasks(
        memory={
            "active_hypotheses": [
                {
                    "id": "hyp-index",
                    "topic": "索引引用",
                    "objective": "核对平面图索引",
                    "source_sheet_no": "A1.01",
                    "target_sheet_nos": ["A4.01"],
                },
                {
                    "id": "hyp-node",
                    "topic": "节点归属",
                    "objective": "核对节点母图",
                    "source_sheet_no": "A1.01",
                    "target_sheet_nos": ["A4.01"],
                },
            ]
        }
    )

    index_task = next(task for task in tasks if task.worker_kind == "index_reference")
    node_task = next(task for task in tasks if task.worker_kind == "node_host_binding")

    assert index_task.context["execution_mode"] == "worker_skill"
    assert index_task.context["skill_id"] == "index_reference"
    assert node_task.context["execution_mode"] == "worker_skill"
    assert node_task.context["skill_id"] == "node_host_binding"


def test_finding_synthesizer_preserves_skill_metadata():
    finding_synthesizer = importlib.import_module("services.audit_runtime.finding_synthesizer")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    findings, escalations = finding_synthesizer.synthesize_findings(
        worker_results=[
            review_task_schema.WorkerResultCard(
                task_id="task-1",
                hypothesis_id="hyp-1",
                worker_kind="index_reference",
                status="confirmed",
                confidence=0.91,
                summary="索引引用成立",
                evidence=[
                    {
                        "sheet_no": "A1.01",
                        "location": "索引D1",
                        "rule_id": "IDX-001",
                        "evidence_pack_id": "overview_pack",
                    }
                ],
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
