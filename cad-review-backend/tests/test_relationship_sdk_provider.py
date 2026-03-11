from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import services.audit.relationship_discovery as relationship_discovery
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.kimi_service import call_kimi


def test_relationship_runner_uses_sdk_provider_when_enabled(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    runner = relationship_discovery._get_relationship_runner("proj-sdk-rel", 5, call_kimi=call_kimi)

    assert runner.provider.provider_name == "sdk"


def test_relationship_runner_prefers_audit_run_provider_mode(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "api")
    monkeypatch.setattr(relationship_discovery, "_load_requested_provider_mode", lambda project_id, audit_version: "kimi_sdk")

    runner = relationship_discovery._get_relationship_runner("proj-sdk-rel-prefers-run", 6, call_kimi=call_kimi)

    assert runner.provider.provider_name == "sdk"
