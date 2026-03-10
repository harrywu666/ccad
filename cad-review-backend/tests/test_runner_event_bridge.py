from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.runner_types import (
    ProviderStreamEvent,
    RunnerTurnRequest,
    RunnerTurnResult,
)


class _FakeProvider:
    provider_name = "fake"

    async def run_once(self, request, subsession):  # noqa: ANN001
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output={"ok": True},
            subsession_key=subsession.session_key,
        )

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        if on_event is not None:
            await on_event(
                ProviderStreamEvent(
                    event_kind="provider_stream_delta",
                    text="AI 引擎正在整理输出",
                    meta={"source": "fake"},
                )
            )
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output={"ok": True},
            subsession_key=subsession.session_key,
        )


def test_runner_provider_stream_delta_is_written_as_event(monkeypatch):
    captured: list[dict] = []

    runner = ProjectAuditAgentRunner(
        project_id="proj-runner-events",
        audit_version=2,
        provider=_FakeProvider(),
    )
    request = RunnerTurnRequest(
        agent_key="master_planner_agent",
        agent_name="总控规划Agent",
        step_key="task_planning",
        progress_hint=18,
        turn_kind="planning",
        system_prompt="sys",
        user_prompt="user",
    )

    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda project_id, audit_version, **kwargs: captured.append(kwargs),
    )

    result = asyncio.run(runner.run_stream(request))

    assert result.output == {"ok": True}
    assert any(event["event_kind"] == "provider_stream_delta" for event in captured)
    assert any(event["event_kind"] == "runner_turn_started" for event in captured)
    assert any(event["event_kind"] == "runner_session_started" for event in captured)
    delta_event = next(event for event in captured if event["event_kind"] == "provider_stream_delta")
    assert delta_event["agent_key"] == "master_planner_agent"
    assert delta_event["message"] == "AI 引擎正在整理输出"
