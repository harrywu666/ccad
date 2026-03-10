from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.runner_types import RunnerTurnRequest


def test_runner_exposes_project_scope_and_subsessions():
    runner = ProjectAuditAgentRunner(project_id="proj-1", audit_version=3, provider=None)
    request = RunnerTurnRequest(
        agent_key="master_planner_agent",
        turn_kind="planning",
        system_prompt="sys",
        user_prompt="user",
    )

    session = runner.resolve_subsession(request)

    assert session.project_id == "proj-1"
    assert session.audit_version == 3
    assert session.agent_key == "master_planner_agent"
