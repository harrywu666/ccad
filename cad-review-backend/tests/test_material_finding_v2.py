from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models import AuditResult
from services.audit.common import to_evidence_json
from services.audit.material_audit import _apply_material_finding


def test_material_worker_v2_applies_structured_finding_fields():
    issue = AuditResult(
        project_id="proj-material-findings",
        audit_version=1,
        type="material",
        severity="error",
        sheet_no_a="A3.01",
        location="材料标注M01",
        description="图纸 A3.01 中使用了材料编号 M01，但材料表中未找到定义。",
        evidence_json=to_evidence_json(
            [
                {
                    "role": "single",
                    "sheet_no": "A3.01",
                    "global_pct": {"x": 48.0, "y": 52.0},
                    "highlight_region": {
                        "shape": "cloud_rect",
                        "bbox_pct": {"x": 45.9, "y": 49.9, "width": 4.2, "height": 4.2},
                    },
                }
            ]
        ),
    )

    _apply_material_finding(issue, review_round=1)

    assert issue.source_agent == "material_review_agent"
    assert issue.finding_type == "material_conflict"
    assert issue.finding_status == "confirmed"
    assert issue.review_round == 1
    assert issue.evidence_pack_id == "focus_pack"
    assert issue.rule_id == "material_missing_definition"
