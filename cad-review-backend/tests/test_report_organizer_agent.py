from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.report_organizer_agent import run_report_organizer_agent


def test_report_organizer_outputs_markdown_sections_for_accepted_findings():
    markdown = run_report_organizer_agent(
        accepted_decisions=[
            {
                "assignment": SimpleNamespace(
                    assignment_id="asg-1",
                    review_intent="elevation_consistency",
                    source_sheet_no="A1.06",
                    target_sheet_nos=["A2.00"],
                    task_title="A1.06 -> A2.00 标高核对",
                ),
                "worker_result": SimpleNamespace(
                    worker_kind="elevation_consistency",
                    summary="标高不一致",
                    confidence=0.91,
                ),
                "final_review_decision": SimpleNamespace(
                    decision="accepted",
                    rationale="定位和证据都足够",
                ),
            }
        ]
    )

    assert "## 问题 1" in markdown
    assert "标高不一致" in markdown
    assert "A1.06" in markdown
