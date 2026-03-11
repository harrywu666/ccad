from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit.index_audit import (  # type: ignore[attr-defined]
    _build_index_agent_report,
)
from services.audit_runtime.runner_types import ProviderStreamEvent, RunnerTurnResult


def test_index_agent_report_requests_runner_help_when_output_is_unstable():
    turn_result = RunnerTurnResult(
        status="error",
        provider_name="sdk",
        output=None,
        error="runner_output_unstable",
        repair_attempts=1,
        events=[
            ProviderStreamEvent(
                event_kind="output_validation_failed",
                text="索引审查Agent 的输出结构不完整",
                meta={},
            )
        ],
    )

    report = _build_index_agent_report(
        turn_result,
        source_sheet_no="A1.01",
        target_sheet_no="A4.01",
        index_no="D1",
    )

    assert report.runner_help_request == "restart_subsession"
    assert report.blocking_issues[0]["kind"] == "unstable_output"
    assert "A1.01" in report.batch_summary
