from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from utils.manual_check_ai_review_flow import (
    _run_mode_env,
    build_shadow_compare_summary,
    resolve_run_modes,
)


def test_shadow_compare_expands_to_legacy_and_chief_review():
    assert resolve_run_modes("legacy") == ["legacy"]
    assert resolve_run_modes("chief_review") == ["chief_review"]
    assert resolve_run_modes("shadow_compare") == ["legacy", "chief_review"]


def test_run_mode_env_forces_legacy_pipeline_only_when_requested():
    legacy_env = _run_mode_env("legacy")
    chief_env = _run_mode_env("chief_review")

    assert legacy_env["AUDIT_FORCE_PIPELINE_MODE"] == "legacy"
    assert legacy_env["AUDIT_LEGACY_PIPELINE_ALLOWED"] == "1"
    assert legacy_env["AUDIT_CHIEF_REVIEW_ENABLED"] == "0"
    assert chief_env["AUDIT_FORCE_PIPELINE_MODE"] is None
    assert chief_env["AUDIT_LEGACY_PIPELINE_ALLOWED"] == "0"
    assert chief_env["AUDIT_CHIEF_REVIEW_ENABLED"] == "1"


def test_shadow_compare_summary_tracks_overlap_and_diff_counts():
    summary = build_shadow_compare_summary(
        {
            "legacy": {
                "checks": {
                    "runtime_audit": {
                        "audit_version": 11,
                        "status": {
                            "started_at": "2026-03-12T10:00:00",
                            "finished_at": "2026-03-12T10:01:30",
                            "status": "done",
                        },
                    }
                },
                "artifacts": {
                    "runtime_results": [
                        {"rule_id": "A", "finding_type": "dim", "location": "L1"},
                        {"rule_id": "B", "finding_type": "mat", "location": "L2"},
                    ]
                },
            },
            "chief_review": {
                "checks": {
                    "runtime_audit": {
                        "audit_version": 12,
                        "status": {
                            "started_at": "2026-03-12T10:00:00",
                            "finished_at": "2026-03-12T10:01:20",
                            "status": "done",
                        },
                    }
                },
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
    assert summary["duration_delta_seconds"] == -10.0
    assert summary["legacy_only_ratio"] == 0.5
    assert summary["chief_review_only_ratio"] == 0.5
    assert summary["ready_for_cutover"] is False
    assert "overlap_below_threshold" in summary["gate_reasons"]


def test_shadow_compare_summary_includes_cutover_recommendation_when_business_signal_is_good():
    summary = build_shadow_compare_summary(
        {
            "legacy": {
                "checks": {
                    "runtime_audit": {
                        "audit_version": 21,
                        "status": {
                            "started_at": "2026-03-12T10:00:00",
                            "finished_at": "2026-03-12T10:01:30",
                            "status": "done",
                        },
                    }
                },
                "artifacts": {
                    "runtime_results": [
                        {"rule_id": "A", "finding_type": "dim", "location": "L1"},
                        {"rule_id": "B", "finding_type": "mat", "location": "L2"},
                        {"rule_id": "C", "finding_type": "idx", "location": "L3"},
                    ]
                },
            },
            "chief_review": {
                "checks": {
                    "runtime_audit": {
                        "audit_version": 22,
                        "status": {
                            "started_at": "2026-03-12T10:00:00",
                            "finished_at": "2026-03-12T10:01:35",
                            "status": "done",
                        },
                    }
                },
                "artifacts": {
                    "runtime_results": [
                        {"rule_id": "A", "finding_type": "dim", "location": "L1"},
                        {"rule_id": "B", "finding_type": "mat", "location": "L2"},
                        {"rule_id": "C", "finding_type": "idx", "location": "L3"},
                    ]
                },
            },
        }
    )

    assert summary["overlap_ratio"] == 1.0
    assert summary["duration_delta_seconds"] == 5.0
    assert summary["ready_for_cutover"] is True
    assert summary["gate_reasons"] == []
