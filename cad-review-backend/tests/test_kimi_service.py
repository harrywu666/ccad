from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import services.kimi_service as kimi_service


def test_http_timeout_config_uses_long_read_timeout(monkeypatch):
    monkeypatch.setenv("KIMI_CONNECT_TIMEOUT_SECONDS", "25")
    monkeypatch.setenv("KIMI_READ_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("KIMI_WRITE_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("KIMI_POOL_TIMEOUT_SECONDS", "15")

    timeout = kimi_service._http_timeout_config()

    assert timeout.connect == 25.0
    assert timeout.read == 600.0
    assert timeout.write == 45.0
    assert timeout.pool == 15.0


def test_provider_defaults_to_official(monkeypatch):
    monkeypatch.delenv("KIMI_PROVIDER", raising=False)

    assert kimi_service._provider() == "official"


def test_resolve_api_key_for_official_supports_moonshot_fallback(monkeypatch):
    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.delenv("KIMI_OFFICIAL_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-secret")

    assert kimi_service._resolve_api_key() == "moonshot-secret"


def test_call_kimi_uses_official_openai_compatible_payload(monkeypatch):
    captured: dict = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"status":"ok","provider":"official"}'
                        }
                    }
                ]
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return DummyResponse()

    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.setenv("KIMI_OFFICIAL_API_KEY", "official-secret")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    result = asyncio.run(
        kimi_service.call_kimi(
            system_prompt="你是 Kimi。",
            user_prompt="请返回 JSON",
            images=[b"\x89PNGrest"],
            temperature=0.0,
            max_tokens=1024,
        )
    )

    assert result == {"status": "ok", "provider": "official"}
    assert captured["url"] == "https://api.moonshot.cn/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer official-secret"
    assert captured["json"]["model"] == "kimi-k2.5"
    assert captured["json"]["temperature"] == 1.0
    assert captured["json"]["messages"][0]["role"] == "system"
    user_parts = captured["json"]["messages"][1]["content"]
    assert user_parts[0]["type"] == "image_url"
    assert user_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert user_parts[1] == {"type": "text", "text": "请返回 JSON"}


def test_call_kimi_uses_code_provider_payload(monkeypatch):
    captured: dict = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "content": [
                    {"type": "text", "text": '{"status":"ok","provider":"code"}'}
                ]
            }

    class DummyClient:
        def __init__(self, *args, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return DummyResponse()

    monkeypatch.setenv("KIMI_PROVIDER", "code")
    monkeypatch.setenv("KIMI_CODE_API_KEY", "code-secret")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    result = asyncio.run(
        kimi_service.call_kimi(
            system_prompt="system",
            user_prompt="user",
            images=[b"\xff\xd8\xff\xe0rest"],
            temperature=0.0,
            max_tokens=2048,
        )
    )

    assert result == {"status": "ok", "provider": "code"}
    assert captured["url"] == "https://api.kimi.com/coding/v1/messages"
    assert captured["headers"]["x-api-key"] == "code-secret"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["json"]["model"] == "k2p5"
    assert captured["json"]["messages"][0]["content"][0]["type"] == "image"
