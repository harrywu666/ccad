from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit.index_audit import _get_index_runner
from services.audit.material_audit import _get_material_runner
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner


def test_index_runner_uses_sdk_provider_when_enabled(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    runner = _get_index_runner("proj-sdk-index", 6)

    assert runner.provider.provider_name == "sdk"


def test_index_runner_prefers_audit_run_provider_mode(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "api")
    monkeypatch.setattr(
        "services.audit.index_audit._load_requested_provider_mode",
        lambda project_id, audit_version: "kimi_sdk",
    )

    runner = _get_index_runner("proj-sdk-index", 6)

    assert runner.provider.provider_name == "sdk"


def test_material_runner_uses_sdk_provider_when_enabled(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    runner = _get_material_runner("proj-sdk-material", 8)

    assert runner.provider.provider_name == "sdk"


def test_material_runner_prefers_audit_run_provider_mode(monkeypatch):
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "api")
    monkeypatch.setattr(
        "services.audit.material_audit._load_requested_provider_mode",
        lambda project_id, audit_version: "kimi_sdk",
    )

    runner = _get_material_runner("proj-sdk-material", 8)

    assert runner.provider.provider_name == "sdk"
