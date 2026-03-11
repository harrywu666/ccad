from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_kimi_sdk_provider_exposes_run_once_and_run_stream():
    from services.audit_runtime.providers.kimi_sdk_provider import KimiSdkProvider

    provider = KimiSdkProvider()

    assert hasattr(provider, "run_once")
    assert hasattr(provider, "run_stream")
    assert provider.provider_name == "sdk"
