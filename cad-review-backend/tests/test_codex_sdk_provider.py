from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_codex_sdk_provider_exposes_run_once_and_run_stream():
    from services.audit_runtime.providers.codex_sdk_provider import CodexSdkProvider

    provider = CodexSdkProvider()

    assert hasattr(provider, "run_once")
    assert hasattr(provider, "run_stream")
    assert hasattr(provider, "cancel")
    assert provider.provider_name == "codex_sdk"
