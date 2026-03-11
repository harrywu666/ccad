from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from utils.manual_check_ai_review_flow import (
    build_shadow_compare_summary,
    resolve_run_modes,
)


def test_shadow_compare_expands_to_legacy_and_chief_review():
    assert resolve_run_modes("legacy") == ["legacy"]
    assert resolve_run_modes("chief_review") == ["chief_review"]
    assert resolve_run_modes("shadow_compare") == ["legacy", "chief_review"]


def test_shadow_compare_summary_tracks_overlap_and_diff_counts():
    summary = build_shadow_compare_summary(
        {
            "legacy": {
                "checks": {"runtime_audit": {"audit_version": 11}},
                "artifacts": {
                    "runtime_results": [
                        {"rule_id": "A", "finding_type": "dim", "location": "L1"},
                        {"rule_id": "B", "finding_type": "mat", "location": "L2"},
                    ]
                },
            },
            "chief_review": {
                "checks": {"runtime_audit": {"audit_version": 12}},
                "artifacts": {
                    "runtime_results": [
                        {"rule_id": "B", "finding_type": "mat", "location": "L2"},
                        {"rule_id": "C", "finding_type": "idx", "location": "L3"},
                    ]
                },
            },
        }
    )

    assert summary["legacy_audit_version"] == 11
    assert summary["chief_review_audit_version"] == 12
    assert summary["overlap_count"] == 1
    assert summary["legacy_only_count"] == 1
    assert summary["chief_review_only_count"] == 1
