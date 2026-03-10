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


def test_observer_snapshot_includes_active_agent_help_reports():
    snapshot = build_observer_snapshot(
        project_id="proj-agent-help",
        audit_version=5,
        runtime_status={"status": "running", "current_step": "尺寸复核"},
        recent_events=[
            {
                "event_kind": "agent_status_reported",
                "agent_key": "dimension_review_agent",
                "agent_name": "尺寸审查Agent",
                "message": "第 3 批尺寸关系结果不稳",
                "meta": {
                    "report_scope": "internal_only",
                    "runner_help_request": "restart_subsession",
                    "blocking_issues": [{"kind": "unstable_output"}],
                    "next_recommended_action": "rerun_current_batch",
                },
            },
            {
                "event_kind": "runner_help_requested",
                "agent_key": "runner_observer_agent",
                "message": "Runner 已收到尺寸审查Agent 的求助请求，正在尝试处理",
                "meta": {
                    "report_scope": "internal_only",
                    "source_agent_key": "dimension_review_agent",
                    "requested_action_name": "restart_subsession",
                },
            },
        ],
    )

    assert snapshot.risk_summary["agent_help_requested_count"] == 1
    assert snapshot.active_agent_reports[0]["agent_key"] == "dimension_review_agent"
    assert snapshot.active_agent_reports[0]["runner_help_request"] == "restart_subsession"
    assert "下属审查Agent 已主动求助" in snapshot.intervention_hint
