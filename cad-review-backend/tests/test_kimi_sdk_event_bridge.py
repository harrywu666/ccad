from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import asyncio

from services.audit_runtime.providers.kimi_sdk_provider import KimiSdkProvider
from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest


class _FakeApproval:
    action = "run shell command"
    description = "test approval"

    def resolve(self, _value):
        return None


class _FakeThink:
    def __init__(self, think: str):
        self.think = think


class _FakeText:
    def __init__(self, text: str):
        self.text = text


class _FakeSession:
    async def prompt(self, _user_input, merge_wire_messages=True):
        yield _FakeThink("先想一下")
        yield _FakeText("hello")
        yield _FakeApproval()
        yield _FakeText(" world")

    async def close(self):
        return None


def test_kimi_sdk_provider_emits_provider_stream_delta_and_phase_event():
    async def _fake_session_factory(**_kwargs):
        return _FakeSession()

    async def _run():
        provider = KimiSdkProvider(session_factory=_fake_session_factory)
        events = []
        request = RunnerTurnRequest(
            agent_key="master_planner_agent",
            agent_name="总控规划Agent",
            turn_kind="planning",
            system_prompt="你是助手",
            user_prompt="请输出内容",
        )
        subsession = RunnerSubsession(
            project_id="proj-1",
            audit_version=1,
            agent_key=request.agent_key,
            session_key="proj-1:1:master_planner_agent",
            shared_context={},
        )

        result = await provider.run_stream(
            request,
            subsession,
            on_event=lambda event: events.append(event),
        )

        assert result.provider_name == "sdk"
        assert result.raw_output == "hello world"
        assert any(event.event_kind == "provider_stream_delta" for event in events)
        assert any(event.event_kind == "phase_event" for event in events)
        assert any("自动批准" in event.text for event in events if event.event_kind == "phase_event")

    asyncio.run(_run())
