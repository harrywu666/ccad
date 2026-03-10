from __future__ import annotations

import asyncio
import inspect
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


class _StreamingProvider:
    provider_name = "fake"

    async def run_once(self, request, subsession):  # noqa: ANN001
        return RunnerTurnResult(provider_name=self.provider_name, output={"ok": True})

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        if on_event is not None:
            maybe_awaitable = on_event(
                ProviderStreamEvent(
                    event_kind="phase_event",
                    text="关系审查Agent 正在推进当前复核",
                    meta={"kind": "progress"},
                )
            )
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

            maybe_awaitable = on_event(
                ProviderStreamEvent(
                    event_kind="provider_stream_delta",
                    text='[{"source":"A-01","target":"A-02"}]',
                )
            )
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=[{"source": "A-01", "target": "A-02"}],
            raw_output='[{"source":"A-01","target":"A-02"}]',
            subsession_key=subsession.session_key,
        )


def _build_request() -> RunnerTurnRequest:
    return RunnerTurnRequest(
        agent_key="relationship_review_agent",
        agent_name="关系审查Agent",
        step_key="relationship_discovery",
        progress_hint=15,
        turn_kind="relationship_candidate_review",
        system_prompt="sys",
        user_prompt="user",
    )


def test_runner_subsession_tracks_last_delta_and_current_phase():
    runner = ProjectAuditAgentRunner(
        project_id="proj-supervisor-state",
        audit_version=3,
        provider=_StreamingProvider(),
    )

    subsession = runner.resolve_subsession(_build_request())

    assert subsession.turn_started_at is None
    assert subsession.last_delta_at is None
    assert subsession.last_progress_at is None
    assert subsession.current_phase == "idle"
    assert subsession.stall_reason is None
    assert subsession.last_broadcast is None


def test_runner_updates_supervisor_state_after_stream_activity():
    runner = ProjectAuditAgentRunner(
        project_id="proj-supervisor-state-run",
        audit_version=4,
        provider=_StreamingProvider(),
    )
    request = _build_request()

    result = asyncio.run(runner.run_stream(request))
    subsession = runner.resolve_subsession(request)

    assert result.status == "ok"
    assert result.output == [{"source": "A-01", "target": "A-02"}]
    assert subsession.turn_started_at is not None
    assert subsession.last_progress_at is not None
    assert subsession.last_delta_at is not None
    assert subsession.current_phase == "idle"
    assert subsession.stall_reason is None
