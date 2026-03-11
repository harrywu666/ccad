from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from utils.manual_check_ai_review_flow import (
    compute_structured_finding_coverage,
    summarize_progressive_metrics,
    summarize_runner_metrics,
)


def test_structured_finding_coverage_uses_required_fields():
    results = [
        {
            "rule_id": "IDX-001",
            "finding_type": "missing_ref",
            "finding_status": "suspected",
            "source_agent": "index_review_agent",
            "evidence_pack_id": "overview_pack",
            "review_round": 1,
            "confidence": 0.7,
        },
        {
            "rule_id": "DIM-001",
            "finding_type": "dim_mismatch",
            "finding_status": "confirmed",
            "source_agent": None,
            "evidence_pack_id": "focus_pack",
            "review_round": 2,
            "confidence": 0.91,
        },
    ]

    coverage = compute_structured_finding_coverage(results)

    assert coverage == 0.5


def test_progressive_metrics_include_round_and_budget_usage():
    tasks = [{"task_type": "index"}, {"task_type": "dimension"}, {"task_type": "material"}]
    results = [
        {
            "review_round": 1,
            "finding_status": "suspected",
            "rule_id": "IDX-001",
            "finding_type": "missing_ref",
            "source_agent": "index_review_agent",
            "evidence_pack_id": "overview_pack",
            "confidence": 0.7,
        },
        {
            "review_round": 2,
            "finding_status": "confirmed",
            "rule_id": "DIM-001",
            "finding_type": "dim_mismatch",
            "source_agent": "dimension_review_agent",
            "evidence_pack_id": "focus_pack",
            "confidence": 0.85,
        },
        {
            "review_round": 3,
            "finding_status": "needs_review",
            "rule_id": "MAT-001",
            "finding_type": "material_conflict",
            "source_agent": "material_review_agent",
            "evidence_pack_id": "focus_pack",
            "confidence": 0.62,
        },
    ]
    events = [
        {"meta": {}},
        {"meta": {"budget_usage": {"image_budget": 188000, "request_budget": 113, "retry_budget": 19}}},
    ]

    metrics = summarize_progressive_metrics(tasks=tasks, results=results, events=events)

    assert metrics["round_2_ratio"] == 0.667
    assert metrics["needs_review_count"] == 1
    assert metrics["budget_usage"]["image_budget"] == 188000
    assert metrics["structured_finding_coverage"] == 1.0


def test_runner_metrics_include_sdk_runtime_counters(monkeypatch):
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")
    events = [
        {"event_kind": "runner_session_started", "meta": {"provider_name": "sdk"}},
        {"event_kind": "runner_session_reused", "meta": {"provider_name": "sdk"}},
        {"event_kind": "output_repair_started", "meta": {"provider_name": "sdk"}},
        {"event_kind": "output_repair_succeeded", "meta": {"provider_name": "sdk"}},
        {"event_kind": "provider_stream_delta", "meta": {"provider_name": "sdk"}},
        {"event_kind": "provider_stream_delta", "meta": {"provider_name": "sdk"}},
        {"event_kind": "runner_turn_deferred", "meta": {"provider_name": "sdk"}},
    ]

    metrics = summarize_runner_metrics(events)

    assert metrics["provider_mode"] == "sdk"
    assert metrics["sdk_session_reuse_count"] == 1
    assert metrics["sdk_repair_attempts"] == 1
    assert metrics["sdk_repair_successes"] == 1
    assert metrics["sdk_needs_review_count"] == 1
    assert metrics["sdk_stream_event_count"] == 2
