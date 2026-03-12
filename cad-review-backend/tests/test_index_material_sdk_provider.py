from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner


def test_index_runner_uses_sdk_provider_when_enabled(monkeypatch):
    index_audit = importlib.import_module("services.audit.index_audit")
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    runner = index_audit._get_index_runner("proj-sdk-index", 6)

    assert runner.provider.provider_name == "sdk"


def test_index_runner_prefers_audit_run_provider_mode(monkeypatch):
    index_audit = importlib.import_module("services.audit.index_audit")
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "api")
    monkeypatch.setattr(
        "services.audit.index_audit._load_requested_provider_mode",
        lambda project_id, audit_version: "kimi_sdk",
    )

    runner = index_audit._get_index_runner("proj-sdk-index", 6)

    assert runner.provider.provider_name == "sdk"


def test_material_runner_uses_sdk_provider_when_enabled(monkeypatch):
    material_audit = importlib.import_module("services.audit.material_audit")
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    runner = material_audit._get_material_runner("proj-sdk-material", 8)

    assert runner.provider.provider_name == "sdk"


def test_material_runner_prefers_audit_run_provider_mode(monkeypatch):
    material_audit = importlib.import_module("services.audit.material_audit")
    ProjectAuditAgentRunner.clear_registry()
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "api")
    monkeypatch.setattr(
        "services.audit.material_audit._load_requested_provider_mode",
        lambda project_id, audit_version: "kimi_sdk",
    )

    runner = material_audit._get_material_runner("proj-sdk-material", 8)

    assert runner.provider.provider_name == "sdk"
