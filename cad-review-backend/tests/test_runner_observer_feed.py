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
