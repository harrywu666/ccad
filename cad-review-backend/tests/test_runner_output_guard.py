from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.output_guard import guard_output
from services.audit_runtime.runner_types import RunnerTurnRequest, RunnerTurnResult


class _FenceProvider:
    provider_name = "fake"

    async def run_once(self, request, subsession):  # noqa: ANN001
        return RunnerTurnResult(provider_name=self.provider_name, output={"ok": True})

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=None,
            status="invalid_output",
            raw_output='```json\n[{"x":1}]\n```',
            subsession_key=subsession.session_key,
            error="无法提取 JSON",
        )


class _BrokenProvider:
    provider_name = "fake"

    async def run_once(self, request, subsession):  # noqa: ANN001
        return RunnerTurnResult(provider_name=self.provider_name, output={"ok": True})

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=None,
            status="invalid_output",
            raw_output="not-json-at-all",
            subsession_key=subsession.session_key,
            error="无法提取 JSON",
        )


def test_runner_repairs_code_fence_json_before_failing():
    repaired = guard_output('```json\n[{"x":1}]\n```')
    assert repaired == [{"x": 1}]


def test_runner_marks_deferred_after_repair_exhausted():
    runner = ProjectAuditAgentRunner(
        project_id="proj-runner-needs-review",
        audit_version=2,
        provider=_BrokenProvider(),
    )
    request = RunnerTurnRequest(
        agent_key="dimension_review_agent",
        agent_name="尺寸审查Agent",
        step_key="dimension",
        progress_hint=60,
        turn_kind="dimension",
        system_prompt="sys",
        user_prompt="user",
    )

    result = asyncio.run(runner.run_stream(request))

    assert result.status == "deferred"
    assert result.repair_attempts == 1


def test_runner_repairs_invalid_output_before_returning():
    runner = ProjectAuditAgentRunner(
        project_id="proj-runner-repair",
        audit_version=2,
        provider=_FenceProvider(),
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

    result = asyncio.run(runner.run_stream(request))

    assert result.status == "ok"
    assert result.output == [{"x": 1}]
    assert result.repair_attempts == 1
