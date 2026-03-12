from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path
import json

import pytest
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit_runtime.finding_schema import (
    Finding,
    GroundingRequiredError,
    apply_finding_to_audit_result,
    finding_from_audit_result,
)


def test_finding_schema_serializes_with_review_round():
    finding = Finding(
        sheet_no="A1.01",
        location="立面图-标注A3",
        rule_id="IDX-001",
        finding_type="missing_ref",
        severity="warning",
        status="suspected",
        confidence=0.62,
        source_agent="index_review_agent",
        evidence_pack_id="pack-1",
        review_round=1,
        triggered_by=None,
        description="首轮发现疑似断链",
    )

    payload = finding.model_dump()

    assert payload["review_round"] == 1
    assert payload["status"] == "suspected"
    assert payload["source_agent"] == "index_review_agent"


def test_finding_schema_rejects_invalid_values():
    with pytest.raises(ValidationError):
        Finding(
            sheet_no="A1.01",
            location="立面图-标注A3",
            rule_id="IDX-001",
            finding_type="not_real_type",
            severity="warning",
            status="suspected",
            confidence=0.62,
            source_agent="index_review_agent",
            evidence_pack_id="pack-1",
            review_round=1,
            triggered_by=None,
            description="首轮发现疑似断链",
        )


def test_finding_from_audit_result_builds_compatible_payload():
    item = SimpleNamespace(
        type="index",
        severity="warning",
        sheet_no_a="A1.01",
        sheet_no_b=None,
        location="索引D1",
        description="图纸 A1.01 中存在疑似断链",
        evidence_json='{"confidence": 0.42, "review_round": 2, "triggered_by": "confidence_low"}',
        rule_id=None,
        finding_type=None,
        finding_status=None,
        source_agent=None,
        evidence_pack_id=None,
        review_round=None,
        triggered_by=None,
        confidence=None,
    )

    finding = finding_from_audit_result(item)

    assert finding.sheet_no == "A1.01"
    assert finding.rule_id == "index_rule"
    assert finding.finding_type == "index_conflict"
    assert finding.source_agent == "index_review_agent"
    assert finding.review_round == 2
    assert finding.triggered_by == "confidence_low"
    assert finding.status == "suspected"


def test_apply_finding_requires_grounded_anchor_regions():
    item = SimpleNamespace(
        evidence_json='{"anchors": [{"role": "source", "sheet_no": "A1.01", "global_pct": {"x": 42.1, "y": 61.2}}]}',
        rule_id=None,
        finding_type=None,
        finding_status=None,
        source_agent=None,
        evidence_pack_id=None,
        review_round=None,
        triggered_by=None,
        confidence=None,
    )
    finding = Finding(
        sheet_no="A1.01",
        location="索引D1",
        rule_id="IDX-001",
        finding_type="missing_ref",
        severity="warning",
        status="confirmed",
        confidence=0.88,
        source_agent="index_review_agent",
        evidence_pack_id="pack-1",
        review_round=1,
        description="图纸 A1.01 中存在断链。",
    )

    apply_finding_to_audit_result(item, finding, require_grounding=True)

    payload = json.loads(item.evidence_json)
    assert payload["grounding"]["status"] == "grounded"


def test_apply_finding_accepts_grounded_anchor_regions():
    item = SimpleNamespace(
        evidence_json=(
            '{"anchors": [{"role": "source", "sheet_no": "A1.01", '
            '"global_pct": {"x": 42.1, "y": 61.2}, '
            '"highlight_region": {"shape": "cloud_rect", "bbox_pct": {"x": 40.0, "y": 59.0, "width": 4.2, "height": 4.2}}}]}'
        ),
        rule_id=None,
        finding_type=None,
        finding_status=None,
        source_agent=None,
        evidence_pack_id=None,
        review_round=None,
        triggered_by=None,
        confidence=None,
    )
    finding = Finding(
        sheet_no="A1.01",
        location="索引D1",
        rule_id="IDX-001",
        finding_type="missing_ref",
        severity="warning",
        status="confirmed",
        confidence=0.88,
        source_agent="index_review_agent",
        evidence_pack_id="pack-1",
        review_round=1,
        description="图纸 A1.01 中存在断链。",
    )

    apply_finding_to_audit_result(item, finding, require_grounding=True)

    payload = json.loads(item.evidence_json)
    assert payload["grounding"]["status"] == "grounded"
    assert payload["grounding"]["anchor_count"] == 1


def test_finding_schema_validate_grounded_evidence_json_accepts_evidence_bundle_anchors():
    from services.audit_runtime.finding_schema import validate_grounded_evidence_json

    payload = json.dumps(
        {
            "evidence_bundle": {
                "anchors": [
                    {
                        "sheet_no": "A1.01",
                        "role": "source",
                        "highlight_region": {
                            "shape": "cloud_rect",
                            "bbox_pct": {"x": 40.0, "y": 59.0, "width": 4.2, "height": 4.2},
                        },
                    }
                ]
            }
        },
        ensure_ascii=False,
    )

    grounded = validate_grounded_evidence_json(payload)

    assert len(grounded) == 1


def test_finding_schema_validate_grounded_evidence_json_accepts_final_issue_finding_anchors():
    from services.audit_runtime.finding_schema import validate_grounded_evidence_json

    payload = json.dumps(
        {
            "finding": {
                "anchors": [
                    {
                        "sheet_no": "A1.01",
                        "role": "source",
                        "highlight_region": {
                            "shape": "cloud_rect",
                            "bbox_pct": {"x": 40.0, "y": 59.0, "width": 4.2, "height": 4.2},
                        },
                    }
                ]
            }
        },
        ensure_ascii=False,
    )

    grounded = validate_grounded_evidence_json(payload)

    assert len(grounded) == 1
