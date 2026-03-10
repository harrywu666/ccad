from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.providers.kimi_api_provider import KimiApiProvider
from services.audit_runtime.providers.kimi_cli_provider import KimiCliProvider


def test_provider_factory_can_build_api_and_cli():
    assert KimiApiProvider().provider_name == "api"
    assert KimiCliProvider(binary="kimi").provider_name == "cli"
