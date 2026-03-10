from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_observer_feed import (  # type: ignore[attr-defined]
    build_observer_snapshot,
)


def test_observer_snapshot_summarizes_project_state_and_recent_events():
    snapshot = build_observer_snapshot(
        project_id="proj-1",
        audit_version=2,
        runtime_status={"status": "running", "current_step": "尺寸复核"},
        recent_events=[
            {
                "event_kind": "runner_broadcast",
                "message": "尺寸审查Agent 正在比对主尺寸链",
            },
            {
                "event_kind": "runner_turn_retrying",
                "message": "Runner 正在重试",
            },
        ],
    )

    assert snapshot.current_step == "尺寸复核"
    assert snapshot.recent_events[0]["event_kind"] == "runner_broadcast"
    assert "observe_only" in snapshot.available_actions


def test_observer_snapshot_exposes_repeated_risk_summary_and_intervention_hint():
    snapshot = build_observer_snapshot(
        project_id="proj-2",
        audit_version=4,
        runtime_status={"status": "running", "current_step": "关系复核"},
        recent_events=[
            {"event_kind": "output_validation_failed", "message": "第一次输出不稳"},
            {"event_kind": "output_repair_succeeded", "message": "第一次修复成功"},
            {"event_kind": "output_validation_failed", "message": "第二次输出不稳"},
            {"event_kind": "output_validation_failed", "message": "第三次输出不稳"},
        ],
    )

    assert snapshot.risk_summary["output_validation_failed_count"] == 3
    assert snapshot.risk_summary["output_unstable_streak"] == 2
    assert "不要继续只做 observe_only" in snapshot.intervention_hint
