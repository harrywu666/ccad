from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_reports import (  # type: ignore[attr-defined]
    AgentStatusReport,
    DimensionAgentReport,
    IndexAgentReport,
    MaterialAgentReport,
    RelationshipAgentReport,
)


def test_dimension_agent_report_accepts_confirmed_suspected_and_blocking_items():
    report = DimensionAgentReport(
        batch_summary="第 2 批尺寸关系已检查",
        confirmed_findings=[{"sheet_no": "A-101"}],
        suspected_findings=[{"sheet_no": "A-102"}],
        blocking_issues=[{"kind": "unstable_output"}],
        runner_help_request="restart_subsession",
        agent_confidence=0.62,
        next_recommended_action="rerun_current_batch",
    )

    assert report.runner_help_request == "restart_subsession"
    assert report.blocking_issues[0]["kind"] == "unstable_output"


def test_generic_agent_reports_share_same_contract():
    relationship = RelationshipAgentReport(
        batch_summary="第 1 批关系候选复核不稳",
        blocking_issues=[{"kind": "unstable_output", "stage": "candidate_review"}],
        runner_help_request="restart_subsession",
        agent_confidence=0.41,
        next_recommended_action="rerun_current_batch",
    )
    generic = AgentStatusReport(
        batch_summary="通用审查进展",
        suspected_findings=[{"sheet_no": "A-201"}],
    )

    assert relationship.runner_help_request == "restart_subsession"
    assert generic.suspected_findings[0]["sheet_no"] == "A-201"
    material = MaterialAgentReport(
        batch_summary="材料审查进展",
        blocking_issues=[{"kind": "unstable_output"}],
    )
    index = IndexAgentReport(
        batch_summary="索引审查进展",
        blocking_issues=[{"kind": "unstable_output"}],
    )
    assert material.blocking_issues[0]["kind"] == "unstable_output"
    assert index.blocking_issues[0]["kind"] == "unstable_output"
