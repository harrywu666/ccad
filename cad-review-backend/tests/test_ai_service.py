from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import services.ai_service as ai_service
from services.audit_runtime.cancel_registry import AuditCancellationRequested


def test_http_timeout_config_uses_long_read_timeout(monkeypatch):
    monkeypatch.setenv("KIMI_CONNECT_TIMEOUT_SECONDS", "25")
    monkeypatch.setenv("KIMI_READ_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("KIMI_WRITE_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("KIMI_POOL_TIMEOUT_SECONDS", "15")

    timeout = ai_service._http_timeout_config()

    assert timeout.connect == 25.0
    assert timeout.read == 600.0
    assert timeout.write == 45.0
    assert timeout.pool == 15.0


def test_provider_defaults_to_official(monkeypatch):
    monkeypatch.delenv("KIMI_PROVIDER", raising=False)

    assert ai_service._provider() == "official"


def test_resolve_api_key_for_official_supports_moonshot_fallback(monkeypatch):
    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.delenv("KIMI_OFFICIAL_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-secret")

    assert ai_service._resolve_api_key() == "moonshot-secret"


def test_resolve_api_key_for_openrouter(monkeypatch):
    monkeypatch.setenv("KIMI_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")

    assert ai_service._resolve_api_key() == "openrouter-secret"


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
        ai_service.call_kimi(
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
        ai_service.call_kimi(
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


def test_call_kimi_uses_openrouter_openai_compatible_payload(monkeypatch):
    captured: dict = {}

    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"status":"ok","provider":"openrouter"}'
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

    monkeypatch.setenv("KIMI_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")
    monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/healer-alpha")
    monkeypatch.setenv("OPENROUTER_REASONING_ENABLED", "1")
    monkeypatch.setenv("OPENROUTER_HTTP_REFERER", "http://localhost:7001")
    monkeypatch.setenv("OPENROUTER_X_TITLE", "ccad-local")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    result = asyncio.run(
        ai_service.call_kimi(
            system_prompt="你是审图助手。",
            user_prompt="请返回 JSON",
            images=[b"\x89PNGrest"],
            temperature=0.2,
            max_tokens=2048,
        )
    )

    assert result == {"status": "ok", "provider": "openrouter"}
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer openrouter-secret"
    assert captured["headers"]["HTTP-Referer"] == "http://localhost:7001"
    assert captured["headers"]["X-OpenRouter-Title"] == "ccad-local"
    assert captured["json"]["model"] == "openrouter/healer-alpha"
    assert captured["json"]["temperature"] == 0.2
    assert captured["json"]["reasoning"] == {"enabled": True}
    assert captured["json"]["messages"][1]["content"][0]["type"] == "image_url"


def test_call_kimi_retries_on_retryable_status(monkeypatch):
    captured: dict = {"attempts": 0, "sleeps": []}

    class DummyResponse:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text
            self.headers = {}

        def json(self):
            return self._payload

    class DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, headers=None, json=None):
            captured["attempts"] += 1
            if captured["attempts"] == 1:
                return DummyResponse(
                    429,
                    text='{"error":{"message":"busy","type":"engine_overloaded_error"}}',
                )
            return DummyResponse(
                200,
                payload={
                    "choices": [
                        {"message": {"content": '{"status":"ok","attempts":2}'}}
                    ]
                },
            )

    async def fake_sleep(seconds):
        captured["sleeps"].append(seconds)

    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.setenv("KIMI_OFFICIAL_API_KEY", "official-secret")
    monkeypatch.setenv("KIMI_MAX_RETRIES", "2")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        ai_service.call_kimi(
            system_prompt="你是 Kimi。",
            user_prompt="请返回 JSON",
        )
    )

    assert result == {"status": "ok", "attempts": 2}
    assert captured["attempts"] == 2
    assert captured["sleeps"] == [2.0]


def test_call_kimi_stream_emits_deltas_and_returns_parsed_json(monkeypatch):
    captured = {"chunks": []}

    class DummyStreamResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_lines(self):
            for line in [
                'data: {"choices":[{"delta":{"content":"{\\"status\\":\\"ok\\","}}]}',
                'data: {"choices":[{"delta":{"content":"\\"provider\\":\\"official\\"}"}}]}',
                "data: [DONE]",
            ]:
                yield line

    class DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, headers=None, json=None):
            return DummyStreamResponse()

    async def on_delta(chunk):
        captured["chunks"].append(chunk)

    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.setenv("KIMI_OFFICIAL_API_KEY", "official-secret")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    result = asyncio.run(
        ai_service.call_kimi_stream(
            system_prompt="你是 Kimi。",
            user_prompt="请返回 JSON",
            on_delta=on_delta,
        )
    )

    assert result == {"status": "ok", "provider": "official"}
    assert captured["chunks"] == ['{"status":"ok",', '"provider":"official"}']


def test_call_kimi_stream_retries_on_429_then_succeeds(monkeypatch):
    captured = {"attempts": 0, "sleeps": []}

    class DummyStreamResponse:
        def __init__(self, status_code, lines=None, text=""):
            self.status_code = status_code
            self.headers = {}
            self._lines = lines or []
            self.text = text

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_lines(self):
            for line in self._lines:
                yield line

    class DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, headers=None, json=None):
            captured["attempts"] += 1
            if captured["attempts"] == 1:
                return DummyStreamResponse(
                    429,
                    text='{"error":{"message":"busy","type":"engine_overloaded_error"}}',
                )
            return DummyStreamResponse(
                200,
                lines=[
                    'data: {"choices":[{"delta":{"content":"{\\"status\\":\\"ok\\"}"}}]}',
                    "data: [DONE]",
                ],
            )

    async def fake_sleep(seconds):
        captured["sleeps"].append(seconds)

    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.setenv("KIMI_OFFICIAL_API_KEY", "official-secret")
    monkeypatch.setenv("KIMI_MAX_RETRIES", "2")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        ai_service.call_kimi_stream(
            system_prompt="你是 Kimi。",
            user_prompt="请返回 JSON",
        )
    )

    assert result == {"status": "ok"}
    assert captured["attempts"] == 2
    assert captured["sleeps"] == [2.0]


def test_call_kimi_stream_reads_error_body_in_stream_mode(monkeypatch):
    captured = {"attempts": 0}

    class DummyStreamResponse:
        def __init__(self, status_code, body: bytes):
            self.status_code = status_code
            self.headers = {}
            self._body = body
            self.text_accessed = False

        @property
        def text(self):
            self.text_accessed = True
            raise AssertionError("stream response text should not be accessed directly")

        async def aread(self):
            return self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_lines(self):
            if False:
                yield None

    class DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, headers=None, json=None):
            captured["attempts"] += 1
            return DummyStreamResponse(502, b'{"error":"upstream bad gateway"}')

    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.setenv("KIMI_OFFICIAL_API_KEY", "official-secret")
    monkeypatch.setenv("KIMI_MAX_RETRIES", "0")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    try:
        asyncio.run(
            ai_service.call_kimi_stream(
                system_prompt="你是 Kimi。",
                user_prompt="请返回 JSON",
            )
        )
    except RuntimeError as exc:
        assert 'AI API 失败 (502): {"error":"upstream bad gateway"}' == str(exc)
    else:
        raise AssertionError("expected RuntimeError")

    assert captured["attempts"] == 1


def test_call_kimi_stream_retries_when_no_new_content_for_too_long(monkeypatch):
    captured = {"attempts": 0, "retries": []}

    class DummyStreamResponse:
        def __init__(self, lines=None, delay=None):
            self.status_code = 200
            self.headers = {}
            self._lines = lines or []
            self._delay = delay

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_lines(self):
            if self._delay is not None:
                await asyncio.sleep(self._delay)
                return
            for line in self._lines:
                yield line

    class DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, headers=None, json=None):
            captured["attempts"] += 1
            if captured["attempts"] == 1:
                return DummyStreamResponse(delay=0.05)
            return DummyStreamResponse(
                lines=[
                    'data: {"choices":[{"delta":{"content":"{\\"status\\":\\"ok\\"}"}}]}',
                    "data: [DONE]",
                ]
            )

    async def on_retry(payload):
        captured["retries"].append(payload["reason"])

    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.setenv("KIMI_OFFICIAL_API_KEY", "official-secret")
    monkeypatch.setenv("KIMI_MAX_RETRIES", "1")
    monkeypatch.setenv("KIMI_STREAM_IDLE_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("KIMI_RETRY_BASE_SECONDS", "0.01")
    monkeypatch.setenv("KIMI_RETRY_MAX_SECONDS", "0.01")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    result = asyncio.run(
        ai_service.call_kimi_stream(
            system_prompt="你是 Kimi。",
            user_prompt="请返回 JSON",
            on_retry=on_retry,
        )
    )

    assert result == {"status": "ok"}
    assert captured["attempts"] == 2
    assert captured["retries"] == ["idle_timeout"]


def test_call_kimi_stream_retries_when_stream_only_emits_non_content_events(monkeypatch):
    captured = {"attempts": 0, "retries": []}

    class DummyStreamResponse:
        def __init__(self, *, endless_non_content=False, lines=None):
            self.status_code = 200
            self.headers = {}
            self._endless_non_content = endless_non_content
            self._lines = lines or []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_lines(self):
            if self._endless_non_content:
                while True:
                    await asyncio.sleep(0.005)
                    yield 'data: {"choices":[{"delta":{"reasoning":"thinking"}}]}'
            for line in self._lines:
                yield line

    class DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, headers=None, json=None):
            captured["attempts"] += 1
            if captured["attempts"] == 1:
                return DummyStreamResponse(endless_non_content=True)
            return DummyStreamResponse(
                lines=[
                    'data: {"choices":[{"delta":{"content":"{\\"status\\":\\"ok\\"}"}}]}',
                    "data: [DONE]",
                ]
            )

    async def on_retry(payload):
        captured["retries"].append(payload["reason"])

    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.setenv("KIMI_OFFICIAL_API_KEY", "official-secret")
    monkeypatch.setenv("KIMI_MAX_RETRIES", "1")
    monkeypatch.setenv("KIMI_STREAM_IDLE_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("KIMI_RETRY_BASE_SECONDS", "0.01")
    monkeypatch.setenv("KIMI_RETRY_MAX_SECONDS", "0.01")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    result = asyncio.run(
        asyncio.wait_for(
            ai_service.call_kimi_stream(
                system_prompt="你是 Kimi。",
                user_prompt="请返回 JSON",
                on_retry=on_retry,
            ),
            timeout=0.2,
        )
    )

    assert result == {"status": "ok"}
    assert captured["attempts"] == 2
    assert captured["retries"] == ["idle_timeout"]


def test_call_kimi_stream_stops_immediately_when_cancel_requested(monkeypatch):
    class DummyStreamResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_lines(self):
            await asyncio.sleep(0.05)
            yield 'data: {"choices":[{"delta":{"content":"{\\"status\\":\\"ok\\"}"}}]}'

    class DummyClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url, headers=None, json=None):
            return DummyStreamResponse()

    monkeypatch.setenv("KIMI_PROVIDER", "official")
    monkeypatch.setenv("KIMI_OFFICIAL_API_KEY", "official-secret")
    monkeypatch.setattr("httpx.AsyncClient", DummyClient)

    async def run():
        return await ai_service.call_kimi_stream(
            system_prompt="你是 Kimi。",
            user_prompt="请返回 JSON",
            should_cancel=lambda: True,
        )

    try:
        asyncio.run(run())
    except AuditCancellationRequested as exc:
        assert "用户手动中断审核" in str(exc)
    else:
        raise AssertionError("expected AuditCancellationRequested")
