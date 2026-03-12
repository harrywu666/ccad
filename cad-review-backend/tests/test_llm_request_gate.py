from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.llm_request_gate import (
    clear_project_llm_gates,
    get_project_llm_gate,
    resolve_llm_gate_provider_key,
)


def setup_function() -> None:
    clear_project_llm_gates()


def test_resolve_llm_gate_provider_key_maps_openrouter_api(monkeypatch):
    monkeypatch.setenv("KIMI_PROVIDER", "openrouter")

    assert (
        resolve_llm_gate_provider_key(provider_mode="api", provider_name="api")
        == "openrouter"
    )


def test_openrouter_gate_uses_dedicated_parallel_limit(monkeypatch):
    monkeypatch.setenv("KIMI_PROVIDER", "openrouter")
    monkeypatch.setenv("AUDIT_PROJECT_LLM_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("AUDIT_PROJECT_OPENROUTER_MAX_CONCURRENCY", "3")

    gate = get_project_llm_gate(
        project_id="proj-openrouter",
        audit_version=1,
        provider_mode="api",
        provider_name="api",
    )

    assert gate.provider_key == "openrouter"
    assert gate.max_concurrency == 3


def test_openrouter_vision_gate_defaults_to_single_concurrency(monkeypatch):
    monkeypatch.setenv("KIMI_PROVIDER", "openrouter")
    monkeypatch.setenv("AUDIT_PROJECT_OPENROUTER_MAX_CONCURRENCY", "4")

    gate = get_project_llm_gate(
        project_id="proj-openrouter-vision",
        audit_version=1,
        provider_mode="api",
        provider_name="api",
        request_has_images=True,
    )

    assert gate.provider_key == "openrouter_vision"
    assert gate.max_concurrency == 1


def test_openrouter_vision_gate_can_use_dedicated_parallel_limit(monkeypatch):
    monkeypatch.setenv("KIMI_PROVIDER", "openrouter")
    monkeypatch.setenv("AUDIT_PROJECT_OPENROUTER_MAX_CONCURRENCY", "4")
    monkeypatch.setenv("AUDIT_PROJECT_OPENROUTER_VISION_MAX_CONCURRENCY", "2")

    gate = get_project_llm_gate(
        project_id="proj-openrouter-vision",
        audit_version=2,
        provider_mode="api",
        provider_name="api",
        request_has_images=True,
    )

    assert gate.provider_key == "openrouter_vision"
    assert gate.max_concurrency == 2


def test_kimi_sdk_gate_uses_dedicated_parallel_limit(monkeypatch):
    monkeypatch.setenv("AUDIT_PROJECT_LLM_MAX_CONCURRENCY", "4")
    monkeypatch.setenv("AUDIT_PROJECT_KIMI_SDK_MAX_CONCURRENCY", "2")

    gate = get_project_llm_gate(
        project_id="proj-sdk",
        audit_version=1,
        provider_mode="kimi_sdk",
        provider_name="sdk",
    )

    assert gate.provider_key == "kimi_sdk"
    assert gate.max_concurrency == 2
