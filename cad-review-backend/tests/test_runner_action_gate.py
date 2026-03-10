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
