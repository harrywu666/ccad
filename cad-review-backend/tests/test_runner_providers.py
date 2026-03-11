from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.providers.kimi_api_provider import KimiApiProvider
from services.audit_runtime.providers.kimi_cli_provider import KimiCliProvider
from services.audit_runtime.providers.kimi_sdk_provider import KimiSdkProvider
from services.audit_runtime.providers.factory import build_runner_provider


def test_provider_factory_can_build_api_and_cli():
    assert KimiApiProvider().provider_name == "api"
    assert KimiCliProvider(binary="kimi").provider_name == "cli"
    assert KimiSdkProvider().provider_name == "sdk"


def test_runner_provider_prefers_cli_in_auto_mode(monkeypatch):
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "auto")
    monkeypatch.setattr(KimiSdkProvider, "is_available", lambda self: False)
    monkeypatch.setattr(KimiCliProvider, "is_available", lambda self: True)

    provider = build_runner_provider()

    assert provider.provider_name == "cli"


def test_runner_provider_prefers_sdk_in_auto_mode(monkeypatch):
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "auto")
    monkeypatch.setattr(KimiSdkProvider, "is_available", lambda self: True)

    provider = build_runner_provider()

    assert provider.provider_name == "sdk"


def test_runner_provider_falls_back_to_api_when_cli_missing(monkeypatch):
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "auto")
    monkeypatch.setattr(KimiSdkProvider, "is_available", lambda self: False)
    monkeypatch.setattr(KimiCliProvider, "is_available", lambda self: False)

    provider = build_runner_provider()

    assert provider.provider_name == "api"


def test_runner_provider_prefers_injected_test_functions_over_sdk(monkeypatch):
    monkeypatch.setenv("AUDIT_RUNNER_PROVIDER", "sdk")

    async def _fake_call_kimi(**kwargs):  # noqa: ANN001
        return {"ok": True}

    provider = build_runner_provider(run_once_func=_fake_call_kimi)

    assert provider.provider_name == "api"
