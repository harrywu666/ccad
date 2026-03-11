from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models import AuditResult
from services.audit.common import to_evidence_json
from services.audit.dimension_audit import _apply_dimension_finding


def test_dimension_worker_v2_applies_structured_finding_fields():
    issue = AuditResult(
        project_id="proj-dim-findings",
        audit_version=1,
        type="dimension",
        severity="warning",
        sheet_no_a="A1.01",
        sheet_no_b="A2.01",
        location="轴网A-1",
        description="A1.01 与 A2.01 的尺寸可能不一致",
        evidence_json=to_evidence_json(
            [
                {
                    "role": "source",
                    "sheet_no": "A1.01",
                    "global_pct": {"x": 18.4, "y": 31.6},
                    "highlight_region": {
                        "shape": "cloud_rect",
                        "bbox_pct": {"x": 16.3, "y": 29.5, "width": 4.2, "height": 4.2},
                    },
                }
            ]
        ),
    )

    _apply_dimension_finding(issue, confidence=0.81, review_round=1)

    assert issue.source_agent == "dimension_review_agent"
    assert issue.rule_id == "dimension_pair_compare"
    assert issue.finding_type == "dim_mismatch"
    assert issue.finding_status == "confirmed"
    assert issue.review_round == 1
    assert issue.evidence_pack_id == "paired_overview_pack"
