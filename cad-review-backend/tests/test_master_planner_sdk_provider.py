from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import services.master_planner_service as master_planner_service
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner


def test_master_planner_runner_uses_sdk_provider_when_enabled(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    runner = master_planner_service._get_master_runner("proj-sdk", 7)

    assert runner.provider.provider_name == "sdk"
