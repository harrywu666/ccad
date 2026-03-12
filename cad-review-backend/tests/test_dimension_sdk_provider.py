from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit.dimension_audit import _get_dimension_runner
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.ai_service import call_kimi


def test_dimension_runner_uses_sdk_provider_when_enabled(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    runner = _get_dimension_runner("proj-sdk-dim", 9, call_kimi=call_kimi)

    assert runner.provider.provider_name == "sdk"
