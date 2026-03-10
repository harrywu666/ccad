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


def test_action_gate_executes_mark_needs_review_callback():
    gate = RunnerActionGate(project_root="/tmp/project")
    called = {"count": 0}

    result = gate.execute(
        "mark_needs_review",
        context={
            "mark_needs_review": lambda: called.__setitem__("count", called["count"] + 1) or "updated",
        },
    )

    assert result["allowed"] is True
    assert result["executed"] is True
    assert result["result"] == "updated"
    assert called["count"] == 1
