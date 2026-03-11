from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit.relationship_discovery import _get_relationship_runner
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner


def test_relationship_runner_uses_sdk_provider_when_enabled(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    runner = _get_relationship_runner("proj-sdk-rel", 5, call_kimi=lambda **kwargs: None)

    assert runner.provider.provider_name == "sdk"
