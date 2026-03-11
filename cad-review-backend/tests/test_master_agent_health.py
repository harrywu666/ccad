from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.master_agent_health import (  # type: ignore[attr-defined]
    MASTER_REPLAN_ANOMALY_THRESHOLD,
    detect_master_behavior_anomaly,
)


def test_detect_master_replan_loop_after_threshold():
    result = detect_master_behavior_anomaly(
        recent_events=[
            {"event_kind": "master_replan_requested", "agent_key": "master_planner_agent"},
            {"event_kind": "master_replan_requested", "agent_key": "master_planner_agent"},
            {"event_kind": "master_replan_requested", "agent_key": "master_planner_agent"},
        ],
        runtime_status={"status": "running", "current_step": "规划审核任务图"},
    )

    assert MASTER_REPLAN_ANOMALY_THRESHOLD == 3
    assert result["is_anomalous"] is True
    assert result["reason"] == "master_replan_loop"

