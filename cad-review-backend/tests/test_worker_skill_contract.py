from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_worker_skill_contract_returns_markdown_conclusion_and_evidence_bundle():
    worker_skill_contract = importlib.import_module("services.audit_runtime.worker_skill_contract")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")
    worker_skill_loader = importlib.import_module("services.audit_runtime.worker_skill_loader")

    result = worker_skill_contract.build_worker_skill_result(
        task=review_task_schema.WorkerTaskCard(
            id="asg-1",
            hypothesis_id="hyp-1",
            worker_kind="elevation_consistency",
            objective="核对 A1.06 与 A2.00",
            source_sheet_no="A1.06",
            target_sheet_nos=["A2.00"],
            context={"assignment_id": "asg-1"},
        ),
        skill_bundle=worker_skill_loader.WorkerSkillBundle(
            worker_kind="elevation_consistency",
            skill_markdown="# skill",
            skill_path=Path("/tmp/elevation/SKILL.md"),
            skill_version="v1",
        ),
        status="confirmed",
        confidence=0.91,
        summary="标高存在冲突",
        rule_id="dimension_pair_compare",
        evidence_pack_id="paired_overview_pack",
        evidence=[{"sheet_no": "A1.06", "location": "轴网 A-1"}],
        anchors=[
            {
                "sheet_no": "A1.06",
                "role": "source",
                "global_pct": {"x": 42.1, "y": 61.2},
            }
        ],
    )

    assert result.markdown_conclusion.startswith("## 任务结论")
    assert result.evidence_bundle["grounding_status"] in {"grounded", "weak", "missing"}
    assert result.evidence_bundle["assignment_id"] == "asg-1"
