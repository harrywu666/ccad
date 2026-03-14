from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.model_gateway import (  # noqa: E402
    InferenceRequest,
    KimiSdkGateway,
    OpenRouterGateway,
    build_model_gateway,
)
from services.review_kernel.policy import ProjectPolicy  # noqa: E402


def test_openrouter_gateway_forces_provider_override():
    captured = {}

    async def fake_call_kimi(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    gateway = OpenRouterGateway(run_once_func=fake_call_kimi)
    request = InferenceRequest(
        system_prompt="sys",
        user_prompt="usr",
        max_tokens=256,
    )
    response = asyncio.run(gateway.multimodal_infer(request))
    assert response.provider == "openrouter"
    assert response.content == {"ok": True}
    assert captured["provider_override"] == "openrouter"


def test_kimi_sdk_gateway_parses_raw_output():
    class FakeSdkProvider:
        async def run_once(self, _request, _subsession):
            return SimpleNamespace(output=None, raw_output='{"picked":"cand-1"}')

    gateway = KimiSdkGateway(provider_factory=lambda: FakeSdkProvider())
    request = InferenceRequest(
        system_prompt="sys",
        user_prompt="usr",
        max_tokens=256,
    )
    response = asyncio.run(gateway.multimodal_infer(request))
    assert response.provider == "kimi_sdk"
    assert response.content == {"picked": "cand-1"}


def test_build_model_gateway_only_two_providers():
    sdk_policy = ProjectPolicy(llm_provider="kimi_sdk")
    openrouter_policy = ProjectPolicy(llm_provider="openrouter")
    assert isinstance(build_model_gateway(sdk_policy), KimiSdkGateway)
    assert isinstance(build_model_gateway(openrouter_policy), OpenRouterGateway)
