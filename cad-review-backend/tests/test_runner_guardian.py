from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_guardian import RunnerGuardian  # type: ignore[attr-defined]
from services.audit_runtime.runner_heartbeat import clear_runner_heartbeat
from services.audit_runtime.runner_observer_session import ProjectRunnerObserverSession
from services.audit_runtime.runner_snapshot_store import write_runner_snapshot


class _FakeProvider:
    provider_name = "sdk"

    async def observe_once(self, snapshot, memory):  # noqa: ANN001
        raise AssertionError("guardian recovery should not call observe_once")


def test_runner_guardian_recovers_session_from_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("CCAD_RUNNER_SNAPSHOT_DIR", str(tmp_path))
    ProjectRunnerObserverSession.clear_registry()
    clear_runner_heartbeat("proj-guardian", 9)

    write_runner_snapshot(
        "proj-guardian",
        9,
        {
            "run_mode": "shadow_chief_review",
            "memory": {
                "project_summary": "Runner 之前已经判断总控在原地打转",
                "current_focus": "规划审核任务图",
                "recent_events": [{"event_kind": "master_replan_requested"}],
                "recent_decisions": [{"suggested_action": "restart_master_agent"}],
                "intervention_history": [{"suggested_action": "restart_master_agent"}],
                "master_status_summary": {"current_step": "规划审核任务图", "progress": 38},
            }
        },
    )

    guardian = RunnerGuardian(timeout_seconds=0)
    result = guardian.check_and_recover("proj-guardian", 9, provider=_FakeProvider())

    session = ProjectRunnerObserverSession.get_or_create(
        "proj-guardian",
        audit_version=9,
        provider=_FakeProvider(),
    )

    assert result["restarted"] is True
    assert result["run_mode"] == "shadow_chief_review"
    assert session.memory.project_summary == "Runner 之前已经判断总控在原地打转"
    assert session.memory.master_status_summary["current_step"] == "规划审核任务图"
