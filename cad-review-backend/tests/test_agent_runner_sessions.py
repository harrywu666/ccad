from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.runner_types import RunnerTurnRequest


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
