from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_action_gate import (  # type: ignore[attr-defined]
    RunnerActionGate,
)


def test_action_gate_allows_restart_subsession_but_rejects_unknown_action():
    gate = RunnerActionGate(project_root="/tmp/project")

    allowed = gate.check_allowed("restart_subsession")
    rejected = gate.check_allowed("delete_workspace")

    assert allowed.allowed is True
    assert rejected.allowed is False


def test_action_gate_executes_restart_subsession_callback():
    gate = RunnerActionGate(project_root="/tmp/project")
    called = {"count": 0}

    result = gate.execute(
        "restart_subsession",
        context={
            "restart_subsession": lambda: called.__setitem__("count", called["count"] + 1) or True,
        },
    )

    assert result["allowed"] is True
    assert result["executed"] is True
    assert result["result"] is True
    assert called["count"] == 1


def test_action_gate_rejects_mark_needs_review_action():
    gate = RunnerActionGate(project_root="/tmp/project")

    result = gate.execute(
        "mark_needs_review",
    )

    assert result["allowed"] is False
    assert result["executed"] is False
    assert result["reason"] == "action_not_allowed"


def test_action_gate_rejects_cancel_turn_and_rerun_current_step_actions():
    gate = RunnerActionGate(project_root="/tmp/project")

    cancel_result = gate.execute("cancel_turn")
    rerun_result = gate.execute("rerun_current_step")

    assert cancel_result["allowed"] is False
    assert cancel_result["reason"] == "action_not_allowed"
    assert rerun_result["allowed"] is False
    assert rerun_result["reason"] == "action_not_allowed"
