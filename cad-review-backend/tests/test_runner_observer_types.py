from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_observer_types import (  # type: ignore[attr-defined]
    RunnerObserverDecision,
    RunnerObserverMemory,
)


def test_runner_observer_decision_exposes_action_and_reason():
    decision = RunnerObserverDecision(
        summary="当前像是假活",
        risk_level="high",
        suggested_action="restart_subsession",
        reason="最近 180 秒没有新正文输出，但步骤仍显示 running",
        should_intervene=True,
        confidence=0.91,
    )

    assert decision.suggested_action == "restart_subsession"
    assert decision.should_intervene is True


def test_runner_observer_memory_tracks_current_summary_and_interventions():
    memory = RunnerObserverMemory(project_id="proj-1", audit_version=3)

    assert memory.project_summary == ""
    assert memory.intervention_history == []
