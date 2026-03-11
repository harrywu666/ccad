from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_observer_feed import build_observer_snapshot
from services.audit_runtime.runner_observer_session import (  # type: ignore[attr-defined]
    ProjectRunnerObserverSession,
)
from services.audit_runtime.runner_observer_types import RunnerObserverDecision


class FakeObserverProvider:
    provider_name = "sdk"

    async def observe_once(self, snapshot, memory):  # noqa: ANN001
        return RunnerObserverDecision(
            summary=f"{snapshot.current_step} 正常推进",
            risk_level="low",
            suggested_action="observe_only",
            reason="最近一直有新输出",
            should_intervene=False,
            confidence=0.88,
            user_facing_broadcast="Runner 正在继续观察当前流程",
        )


def test_observer_session_reuses_same_instance_per_project():
    ProjectRunnerObserverSession.clear_registry()

    s1 = ProjectRunnerObserverSession.get_or_create(
        "proj-1",
        audit_version=1,
        provider=FakeObserverProvider(),
    )
    s2 = ProjectRunnerObserverSession.get_or_create(
        "proj-1",
        audit_version=1,
        provider=FakeObserverProvider(),
    )

    assert s1 is s2


def test_observer_session_updates_memory_after_observe():
    ProjectRunnerObserverSession.clear_registry()
    session = ProjectRunnerObserverSession.get_or_create(
        "proj-2",
        audit_version=3,
        provider=FakeObserverProvider(),
    )
    snapshot = build_observer_snapshot(
        project_id="proj-2",
        audit_version=3,
        runtime_status={"status": "running", "current_step": "尺寸复核"},
        recent_events=[
            {"event_kind": "runner_broadcast", "message": "尺寸审查Agent 正在比对主尺寸链"},
        ],
    )

    decision = asyncio.run(session.observe(snapshot))

    assert decision.suggested_action == "observe_only"
    assert session.memory.project_summary == "尺寸复核 正常推进"
    assert session.memory.recent_events[-1]["event_kind"] == "runner_broadcast"
    assert session.memory.recent_decisions[-1]["suggested_action"] == "observe_only"


def test_observer_session_debounces_frequent_llm_calls(monkeypatch):
    ProjectRunnerObserverSession.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_OBSERVER_MIN_INTERVAL_SECONDS", "60")

    session = ProjectRunnerObserverSession.get_or_create(
        "proj-3",
        audit_version=4,
        provider=FakeObserverProvider(),
        provider_mode="kimi_sdk",
    )

    assert session.should_observe() is True

    snapshot = build_observer_snapshot(
        project_id="proj-3",
        audit_version=4,
        runtime_status={"status": "running", "current_step": "关系复核"},
        recent_events=[],
    )
    asyncio.run(session.observe(snapshot))

    assert session.should_observe() is False
