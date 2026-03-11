from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.cancel_registry import AuditCancellationRequested
from services.audit_runtime.providers.kimi_sdk_provider import SdkStreamIdleTimeoutError
from services.audit_runtime.runner_types import RunnerTurnRequest, RunnerTurnResult
from services.audit_runtime.visual_budget import (
    VisualBudget,
    set_active_visual_budget,
)


class _TimeoutProvider:
    provider_name = "sdk"

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def run_once(self, request, subsession):  # noqa: ANN001
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output={"ok": True},
            subsession_key=subsession.session_key,
        )

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        self.calls += 1
        if self.calls <= self.fail_times:
            raise SdkStreamIdleTimeoutError(
                idle_seconds=12.0,
                session_key=subsession.session_key,
            )
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output={"ok": True, "attempt": self.calls},
            subsession_key=subsession.session_key,
        )


class _CancelledProvider:
    provider_name = "sdk"

    async def run_once(self, request, subsession):  # noqa: ANN001
        raise AuditCancellationRequested("用户手动中断审核")

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        raise AuditCancellationRequested("用户手动中断审核")


def _build_request() -> RunnerTurnRequest:
    return RunnerTurnRequest(
        agent_key="relationship_review_agent",
        agent_name="关系审查Agent",
        step_key="relationship_discovery",
        progress_hint=15,
        turn_kind="relationship_candidate_review",
        system_prompt="sys",
        user_prompt="user",
        meta={"candidate_index": 15, "candidate_total": 20},
    )


def test_runner_retries_stalled_turn_before_retry_budget_is_exhausted(monkeypatch):
    provider = _TimeoutProvider(fail_times=1)
    runner = ProjectAuditAgentRunner(
        project_id="proj-runner-stall-retry",
        audit_version=1,
        provider=provider,
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda project_id, audit_version, **kwargs: captured.append(kwargs),
    )

    budget = VisualBudget(retry_budget=1)
    set_active_visual_budget(budget)
    try:
        result = asyncio.run(runner.run_stream(_build_request()))
    finally:
        set_active_visual_budget(None)

    assert result.status == "ok"
    assert result.output == {"ok": True, "attempt": 2}
    assert provider.calls == 2
    assert budget.retry_budget == 0
    assert any(event["event_kind"] == "runner_turn_retrying" for event in captured)


def test_runner_retries_stalled_turn_and_marks_deferred_after_limit(monkeypatch):
    provider = _TimeoutProvider(fail_times=2)
    runner = ProjectAuditAgentRunner(
        project_id="proj-runner-stall-needs-review",
        audit_version=2,
        provider=provider,
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda project_id, audit_version, **kwargs: captured.append(kwargs),
    )

    budget = VisualBudget(retry_budget=1)
    set_active_visual_budget(budget)
    try:
        result = asyncio.run(runner.run_stream(_build_request()))
    finally:
        set_active_visual_budget(None)

    assert result.status == "deferred"
    assert result.repair_attempts == 0
    assert provider.calls == 2
    assert budget.retry_budget == 0
    assert any(event["event_kind"] == "runner_turn_deferred" for event in captured)


def test_runner_prioritizes_cancellation_over_failure_handling(monkeypatch):
    runner = ProjectAuditAgentRunner(
        project_id="proj-runner-cancel",
        audit_version=3,
        provider=_CancelledProvider(),
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda project_id, audit_version, **kwargs: captured.append(kwargs),
    )

    with pytest.raises(AuditCancellationRequested, match="用户手动中断审核"):
        asyncio.run(runner.run_stream(_build_request()))

    assert not any(event["event_kind"] == "runner_session_failed" for event in captured)
