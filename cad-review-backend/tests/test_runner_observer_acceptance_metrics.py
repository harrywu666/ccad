from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from utils.manual_check_ai_review_flow import summarize_runner_metrics


def test_runner_metrics_include_observer_decision_counts():
    metrics = summarize_runner_metrics(
        [
            {"event_kind": "runner_observer_decision", "meta": {"provider_name": "sdk"}},
            {"event_kind": "runner_broadcast", "meta": {"provider_name": "sdk"}},
            {
                "event_kind": "runner_observer_decision",
                "meta": {"provider_name": "sdk", "suggested_action": "restart_subsession", "should_intervene": True},
            },
        ],
        requested_provider_mode="sdk",
        runtime_status={"provider_mode": "sdk"},
    )

    assert metrics["observer_decision_count"] == 2
    assert metrics["observer_intervention_suggested_count"] == 1
