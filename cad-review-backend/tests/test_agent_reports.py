from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_reports import (  # type: ignore[attr-defined]
    DimensionAgentReport,
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
