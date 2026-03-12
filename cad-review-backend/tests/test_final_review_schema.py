from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.final_review_schema import FinalIssue


def _build_payload(*, anchors: list[dict]) -> dict:
    return {
        "issue_code": "ISS-001",
        "title": "标高不一致",
        "description": "入口立面与节点详图标高写法不一致",
        "severity": "warning",
        "finding_type": "dim_mismatch",
        "disposition": "accepted",
        "source_agent": "organizer_agent",
        "source_assignment_id": "asg-1",
        "source_sheet_no": "A1.06",
        "target_sheet_nos": ["A2.00"],
        "location_text": "入口立面附近",
        "evidence_pack_id": "pack-1",
        "anchors": anchors,
        "confidence": 0.91,
        "review_round": 1,
        "organizer_markdown_block": "## 问题 1\n- 标高不一致",
    }


def test_final_issue_rejects_empty_anchors():
    with pytest.raises(ValidationError):
        FinalIssue(**_build_payload(anchors=[]))


def test_final_issue_rejects_invalid_anchor_payload():
    with pytest.raises(ValidationError):
        FinalIssue(
            **_build_payload(
                anchors=[
                    {
                        "sheet_no": "A1.06",
                        "role": "source",
                    }
                ]
            )
        )


def test_final_issue_accepts_anchor_with_global_pct():
    issue = FinalIssue(
        **_build_payload(
            anchors=[
                {
                    "sheet_no": "A1.06",
                    "role": "source",
                    "global_pct": {"x": 42.1, "y": 61.2},
                }
            ]
        )
    )

    assert issue.anchors[0].global_pct is not None


def test_final_issue_accepts_anchor_with_highlight_region_bbox():
    issue = FinalIssue(
        **_build_payload(
            anchors=[
                {
                    "sheet_no": "A1.06",
                    "role": "source",
                    "highlight_region": {
                        "shape": "cloud_rect",
                        "bbox_pct": {"x": 40.0, "y": 59.0, "width": 4.2, "height": 4.2},
                    },
                }
            ]
        )
    )

    assert issue.anchors[0].highlight_region is not None


def test_final_issue_ignores_legacy_highlight_region_origin():
    issue = FinalIssue(
        **_build_payload(
            anchors=[
                {
                    "sheet_no": "A1.06",
                    "role": "source",
                    "highlight_region": {
                        "shape": "cloud_rect",
                        "origin": "dimension",
                        "bbox_pct": {"x": 40.0, "y": 59.0, "width": 4.2, "height": 4.2},
                    },
                }
            ]
        )
    )

    assert issue.anchors[0].highlight_region is not None
