from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.providers.kimi_sdk_provider import (
    KimiSdkProvider,
    SdkStreamIdleTimeoutError,
    _idle_timeout_seconds,
    _sdk_rate_limit_cooldown_seconds,
    _sdk_max_concurrency,
)
from services.audit_runtime.cancel_registry import AuditCancellationRequested
from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest


class _FakeText:
    def __init__(self, text: str):
        self.text = text


class _IdleSession:
    def __init__(self) -> None:
        self.cancelled = False

    async def prompt(self, _user_input, merge_wire_messages=True):
        yield _FakeText("hello")
        await asyncio.sleep(0.05)
        yield _FakeText(" world")

    def cancel(self):
        self.cancelled = True

    async def close(self):
        return None


class _SilentSession:
    def __init__(self) -> None:
        self.cancelled = False

    async def prompt(self, _user_input, merge_wire_messages=True):
        await asyncio.sleep(10)
        if False:
            yield None

    def cancel(self):
        self.cancelled = True

    async def close(self):
        return None


def test_sdk_provider_times_out_when_stream_has_no_new_delta(monkeypatch):
    monkeypatch.setenv("AUDIT_SDK_STREAM_IDLE_TIMEOUT_SECONDS", "0.01")
    session = _IdleSession()

    async def _fake_session_factory(**_kwargs):
        return session

    async def _run():
        provider = KimiSdkProvider(session_factory=_fake_session_factory)
        request = RunnerTurnRequest(
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            turn_kind="relationship_candidate_review",
            system_prompt="你是助手",
            user_prompt="请输出 JSON",
        )
        subsession = RunnerSubsession(
            project_id="proj-sdk-timeout",
            audit_version=1,
            agent_key=request.agent_key,
            session_key="proj-sdk-timeout:1:relationship_review_agent",
            shared_context={},
        )

        with pytest.raises(SdkStreamIdleTimeoutError):
            await provider.run_stream(request, subsession)

        assert session.cancelled is True

    asyncio.run(_run())


def test_sdk_provider_can_cancel_while_stream_is_silent(monkeypatch):
    monkeypatch.delenv("AUDIT_SDK_STREAM_IDLE_TIMEOUT_SECONDS", raising=False)
    session = _SilentSession()

    async def _fake_session_factory(**_kwargs):
        return session

    async def _run():
        provider = KimiSdkProvider(session_factory=_fake_session_factory)
        request = RunnerTurnRequest(
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            turn_kind="relationship_candidate_review",
            system_prompt="你是助手",
            user_prompt="请输出 JSON",
        )
        subsession = RunnerSubsession(
            project_id="proj-sdk-cancel",
            audit_version=1,
            agent_key=request.agent_key,
            session_key="proj-sdk-cancel:1:relationship_review_agent",
            shared_context={},
        )

        cancel_state = {"value": False}

        async def _trigger_cancel():
            await asyncio.sleep(0.05)
            cancel_state["value"] = True

        trigger = asyncio.create_task(_trigger_cancel())
        started = asyncio.get_running_loop().time()
        with pytest.raises(AuditCancellationRequested, match="用户手动中断审核"):
            await provider.run_stream(
                request,
                subsession,
                should_cancel=lambda: cancel_state["value"],
            )
        elapsed = asyncio.get_running_loop().time() - started
        await trigger

        assert elapsed < 1.0
        assert session.cancelled is True

    asyncio.run(_run())


def test_sdk_provider_uses_nonzero_default_idle_timeout(monkeypatch):
    monkeypatch.delenv("AUDIT_SDK_STREAM_IDLE_TIMEOUT_SECONDS", raising=False)

    assert _idle_timeout_seconds() == 45.0


def test_sdk_provider_uses_bounded_default_global_concurrency(monkeypatch):
    monkeypatch.delenv("AUDIT_KIMI_SDK_MAX_CONCURRENCY", raising=False)
    assert _sdk_max_concurrency() == 6

    monkeypatch.setenv("AUDIT_KIMI_SDK_MAX_CONCURRENCY", "99")
    assert _sdk_max_concurrency() == 30


def test_sdk_provider_uses_default_rate_limit_cooldown(monkeypatch):
    monkeypatch.delenv("AUDIT_KIMI_SDK_RATE_LIMIT_COOLDOWN_SECONDS", raising=False)

    assert _sdk_rate_limit_cooldown_seconds() == 20.0


def test_sdk_provider_retries_after_rate_limit(monkeypatch):
    monkeypatch.setenv("AUDIT_KIMI_SDK_RATE_LIMIT_COOLDOWN_SECONDS", "0.01")
    monkeypatch.setenv("AUDIT_KIMI_SDK_RATE_LIMIT_RETRY_LIMIT", "1")

    class _RetryOnceSession:
        def __init__(self) -> None:
            self.prompt_calls = 0

        async def prompt(self, _user_input, merge_wire_messages=True):
            self.prompt_calls += 1
            if self.prompt_calls == 1:
                raise RuntimeError(
                    "Error code: 429 - {'error': {'message': 'Too Many Requests', 'type': 'rate_limit_reached_error'}}"
                )
            yield _FakeText("[]")

        async def close(self):
            return None

        def cancel(self):
            return None

    session = _RetryOnceSession()

    async def _fake_session_factory(**_kwargs):
        return session

    async def _run():
        provider = KimiSdkProvider(session_factory=_fake_session_factory)
        request = RunnerTurnRequest(
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            turn_kind="relationship_candidate_review",
            system_prompt="你是助手",
            user_prompt="请输出 JSON",
        )
        subsession = RunnerSubsession(
            project_id="proj-sdk-rate-limit",
            audit_version=1,
            agent_key=request.agent_key,
            session_key="proj-sdk-rate-limit:1:relationship_review_agent",
            shared_context={},
        )

        result = await provider.run_stream(request, subsession)

        assert session.prompt_calls == 2
        assert result.raw_output == "[]"

    asyncio.run(_run())


def test_sdk_provider_can_restart_subsession_with_fresh_session():
    created_sessions = []

    class _RestartableSession:
        def __init__(self) -> None:
            self.cancelled = False
            self.closed = False

        async def prompt(self, _user_input, merge_wire_messages=True):
            yield _FakeText("hello")

        def cancel(self):
            self.cancelled = True

        async def close(self):
            self.closed = True

    async def _fake_session_factory(**_kwargs):
        session = _RestartableSession()
        created_sessions.append(session)
        return session

    async def _run():
        provider = KimiSdkProvider(session_factory=_fake_session_factory)
        subsession = RunnerSubsession(
            project_id="proj-sdk-restart",
            audit_version=1,
            agent_key="relationship_review_agent",
            session_key="proj-sdk-restart:1:relationship_review_agent",
            shared_context={},
        )

        first = await provider._get_or_create_session(subsession)
        restarted = await provider.restart_subsession(subsession)
        second = await provider._get_or_create_session(subsession)

        assert restarted is True
        assert first is not second
        assert first.cancelled is True
        assert first.closed is True

    asyncio.run(_run())
