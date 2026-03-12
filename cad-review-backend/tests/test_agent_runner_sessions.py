from __future__ import annotations

import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.llm_request_gate import clear_project_llm_gates
from services.audit_runtime.runner_types import RunnerTurnRequest


class _Provider:
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name


def test_runner_uses_subsessions_per_agent():
    runner = ProjectAuditAgentRunner(project_id="proj-1", audit_version=1, provider=None)

    planning = runner.resolve_subsession(
        RunnerTurnRequest(
            agent_key="master_planner_agent",
            turn_kind="planning",
            system_prompt="s",
            user_prompt="u",
        )
    )
    dimension = runner.resolve_subsession(
        RunnerTurnRequest(
            agent_key="dimension_review_agent",
            turn_kind="dimension",
            system_prompt="s",
            user_prompt="u",
        )
    )

    assert planning.session_key != dimension.session_key
    assert planning.project_id == dimension.project_id == "proj-1"


def test_runner_factory_returns_same_instance_for_same_project():
    runner_1 = ProjectAuditAgentRunner.get_or_create("proj-1", audit_version=1, provider=None)
    runner_2 = ProjectAuditAgentRunner.get_or_create("proj-1", audit_version=1, provider=None)

    assert runner_1 is runner_2


def test_runner_factory_keeps_first_non_null_provider_for_same_project():
    ProjectAuditAgentRunner.clear_registry()

    runner_1 = ProjectAuditAgentRunner.get_or_create(
        "proj-1",
        audit_version=1,
        provider=_Provider("sdk"),
    )
    runner_2 = ProjectAuditAgentRunner.get_or_create(
        "proj-1",
        audit_version=1,
        provider=_Provider("api"),
    )

    assert runner_1 is runner_2
    assert runner_2.provider.provider_name == "sdk"


def test_runner_supports_multiple_subsessions_for_same_agent_when_meta_key_present():
    runner = ProjectAuditAgentRunner(project_id="proj-1", audit_version=1, provider=None)

    sheet_a = runner.resolve_subsession(
        RunnerTurnRequest(
            agent_key="dimension_review_agent",
            turn_kind="dimension_sheet_semantic",
            system_prompt="s",
            user_prompt="u",
            meta={"subsession_key": "sheet_semantic:A101"},
        )
    )
    sheet_b = runner.resolve_subsession(
        RunnerTurnRequest(
            agent_key="dimension_review_agent",
            turn_kind="dimension_sheet_semantic",
            system_prompt="s",
            user_prompt="u",
            meta={"subsession_key": "sheet_semantic:A401"},
        )
    )

    assert sheet_a is not sheet_b
    assert sheet_a.session_key != sheet_b.session_key
    assert sheet_a.session_key.endswith("dimension_review_agent:sheet_semantic:A101")
    assert sheet_b.session_key.endswith("dimension_review_agent:sheet_semantic:A401")


def test_runner_can_isolate_worker_subsessions_with_same_agent_key():
    runner = ProjectAuditAgentRunner(project_id="proj-1", audit_version=1, provider=None)

    worker_a = runner.resolve_subsession(
        RunnerTurnRequest(
            agent_key="review_worker_agent",
            turn_kind="worker",
            system_prompt="s",
            user_prompt="u",
            meta={"subsession_key": "review_worker_agent:task-a"},
        )
    )
    worker_b = runner.resolve_subsession(
        RunnerTurnRequest(
            agent_key="review_worker_agent",
            turn_kind="worker",
            system_prompt="s",
            user_prompt="u",
            meta={"subsession_key": "review_worker_agent:task-b"},
        )
    )

    assert worker_a.session_key != worker_b.session_key


def test_runner_serializes_llm_turns_with_project_gate(monkeypatch):
    clear_project_llm_gates()
    monkeypatch.setenv("AUDIT_PROJECT_LLM_MAX_CONCURRENCY", "1")
    monkeypatch.setenv("AUDIT_PROJECT_LLM_MIN_INTERVAL_SECONDS", "0")

    class _AsyncProvider:
        provider_name = "sdk"

        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def run_once(self, request, subsession):  # noqa: ANN001
            del request, subsession
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.02)
            self.active -= 1
            return type("Result", (), {"provider_name": "sdk", "output": [], "status": "ok"})()

    async def _run():
        provider = _AsyncProvider()
        runner = ProjectAuditAgentRunner(
            project_id="proj-gate",
            audit_version=1,
            provider=provider,
            shared_context={"provider_mode": "kimi_sdk"},
        )
        request_a = RunnerTurnRequest(
            agent_key="dimension_review_agent",
            agent_name="尺寸审查Agent",
            turn_kind="dimension_pair_compare",
            system_prompt="s",
            user_prompt="u",
            meta={"subsession_key": "pair:A"},
        )
        request_b = RunnerTurnRequest(
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            turn_kind="relationship_candidate_review",
            system_prompt="s",
            user_prompt="u",
            meta={"subsession_key": "candidate:B"},
        )
        await asyncio.gather(
            runner.run_once(request_a),
            runner.run_once(request_b),
        )
        assert provider.max_active == 1

    asyncio.run(_run())
