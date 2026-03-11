from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.runner_types import RunnerTurnRequest, RunnerTurnResult


class _FenceProvider:
    provider_name = "sdk"

    async def run_once(self, request, subsession):  # noqa: ANN001
        return RunnerTurnResult(provider_name=self.provider_name, output={"ok": True})

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=None,
            status="invalid_output",
            raw_output='```json\n{"ok": true}\n```',
            subsession_key=subsession.session_key,
            error="无法提取 JSON",
        )


class _BrokenProvider:
    provider_name = "sdk"

    async def run_once(self, request, subsession):  # noqa: ANN001
        return RunnerTurnResult(provider_name=self.provider_name, output={"ok": True})

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=None,
            status="invalid_output",
            raw_output="still-not-json",
            subsession_key=subsession.session_key,
            error="无法提取 JSON",
        )


def _request() -> RunnerTurnRequest:
    return RunnerTurnRequest(
        agent_key="dimension_review_agent",
        agent_name="尺寸审查Agent",
        step_key="dimension",
        progress_hint=60,
        turn_kind="dimension",
        system_prompt="sys",
        user_prompt="user",
    )


def test_kimi_sdk_invalid_json_is_repaired():
    runner = ProjectAuditAgentRunner(
        project_id="proj-sdk-repair",
        audit_version=1,
        provider=_FenceProvider(),
    )

    result = asyncio.run(runner.run_stream(_request()))

    assert result.status == "ok"
    assert result.output == {"ok": True}
    assert result.repair_attempts == 1


def test_kimi_sdk_invalid_json_is_marked_deferred_when_unrepairable():
    runner = ProjectAuditAgentRunner(
        project_id="proj-sdk-needs-review",
        audit_version=1,
        provider=_BrokenProvider(),
    )

    result = asyncio.run(runner.run_stream(_request()))

    assert result.status == "deferred"
    assert result.output is None
    assert result.repair_attempts == 1
