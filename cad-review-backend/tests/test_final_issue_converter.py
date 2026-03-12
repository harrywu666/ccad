from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.final_issue_converter import convert_markdown_and_evidence_to_final_issues


def test_final_issue_converter_combines_markdown_and_evidence_bundle():
    issues = convert_markdown_and_evidence_to_final_issues(
        organizer_markdown=(
            "## 问题 1\n"
            "- 标题：标高不一致\n"
            "- 描述：A1.06 与 A2.00 标高冲突\n"
            "- 建议：复核标高链路\n"
        ),
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
                    hypothesis_id="hyp-1",
                    worker_kind="elevation_consistency",
                    summary="A1.06 与 A2.00 标高冲突",
                    confidence=0.91,
                    markdown_conclusion="## 任务结论\n- 标高不一致",
                    evidence_bundle={
                        "assignment_id": "asg-1",
                        "evidence_pack_id": "paired_overview_pack",
                        "grounding_status": "grounded",
                        "review_round": 2,
                        "anchors": [
                            {
                                "sheet_no": "A1.06",
                                "role": "source",
                                "highlight_region": {
                                    "shape": "rect",
                                    "bbox_pct": {
                                        "x": 11.0,
                                        "y": 22.0,
                                        "width": 15.0,
                                        "height": 8.0,
                                    },
                                },
                            }
                        ],
                    },
                    meta={"severity": "warning"},
                ),
                "final_review_decision": SimpleNamespace(
                    decision="accepted",
                    rationale="定位和证据都足够",
                    evidence_pack_id="paired_overview_pack",
                ),
            }
        ],
    )

    assert len(issues) == 1
    assert issues[0].issue_code.startswith("ISS-")
    assert issues[0].source_agent == "organizer_agent"
    assert issues[0].organizer_markdown_block.startswith("## 问题 1")
    assert issues[0].anchors[0].highlight_region.bbox_pct.width > 0
