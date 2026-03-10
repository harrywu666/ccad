from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_observer_prompt import (  # type: ignore[attr-defined]
    build_runner_observer_user_prompt,
    build_runner_observer_system_prompt,
)
from services.audit_runtime.runner_observer_feed import build_observer_snapshot
from services.audit_runtime.runner_observer_types import RunnerObserverMemory


def test_runner_observer_prompt_includes_agent_and_soul_sections():
    prompt = build_runner_observer_system_prompt()

    assert "项目级 Runner Observer Agent" in prompt
    assert "你是整轮审图的 AI 值班长" in prompt


def test_runner_observer_user_prompt_includes_escalation_hint_and_recent_decisions():
    snapshot = build_observer_snapshot(
        project_id="proj-prompt",
        audit_version=2,
        runtime_status={"status": "running", "current_step": "关系复核"},
        recent_events=[
            {"event_kind": "output_validation_failed", "message": "第一次输出不稳"},
            {"event_kind": "output_validation_failed", "message": "第二次输出不稳"},
        ],
    )
    memory = RunnerObserverMemory(
        project_id="proj-prompt",
        audit_version=2,
        recent_decisions=[
            {"suggested_action": "observe_only", "risk_level": "medium"},
            {"suggested_action": "observe_only", "risk_level": "medium"},
        ],
    )

    prompt = build_runner_observer_user_prompt(snapshot, memory)

    assert "不要连续多次只给 observe_only" in prompt
    assert "recent_decisions" in prompt


def test_runner_observer_user_prompt_includes_decision_pressure_summary():
    snapshot = build_observer_snapshot(
        project_id="proj-pressure",
        audit_version=3,
        runtime_status={"status": "running", "current_step": "关系复核"},
        recent_events=[
            {"event_kind": "output_validation_failed", "message": "第一次输出不稳"},
            {"event_kind": "output_validation_failed", "message": "第二次输出不稳"},
            {"event_kind": "output_validation_failed", "message": "第三次输出不稳"},
        ],
    )
    memory = RunnerObserverMemory(
        project_id="proj-pressure",
        audit_version=3,
        recent_decisions=[
            {"suggested_action": "observe_only", "risk_level": "medium"},
            {"suggested_action": "observe_only", "risk_level": "medium"},
            {"suggested_action": "observe_only", "risk_level": "medium"},
        ],
    )

    prompt = build_runner_observer_user_prompt(snapshot, memory)

    assert "decision_pressure" in prompt
    assert "连续 3 次仍以 observe_only 收敛" in prompt
