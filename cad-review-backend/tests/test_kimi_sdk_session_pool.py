from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.providers.kimi_sdk_provider import KimiSdkProvider
from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest


def test_runner_factory_returns_same_instance_for_same_project():
    ProjectAuditAgentRunner.clear_registry()

    r1 = ProjectAuditAgentRunner.get_or_create("proj-1", audit_version=1, provider=None)
    r2 = ProjectAuditAgentRunner.get_or_create("proj-1", audit_version=1, provider=None)

    assert r1 is r2


def test_kimi_sdk_provider_uses_independent_subsessions_per_agent():
    provider = KimiSdkProvider()
    sub_a = RunnerSubsession(
        project_id="proj-1",
        audit_version=1,
        agent_key="relationship_review_agent",
        session_key="proj-1:1:relationship_review_agent",
        shared_context={},
    )
    sub_b = RunnerSubsession(
        project_id="proj-1",
        audit_version=1,
        agent_key="dimension_review_agent",
        session_key="proj-1:1:dimension_review_agent",
        shared_context={},
    )

    key_a = provider._session_store_key(sub_a)
    key_b = provider._session_store_key(sub_b)

    assert key_a != key_b


def test_kimi_sdk_provider_reuses_same_subsession_key_for_same_agent():
    provider = KimiSdkProvider()
    sub = RunnerSubsession(
        project_id="proj-1",
        audit_version=1,
        agent_key="relationship_review_agent",
        session_key="proj-1:1:relationship_review_agent",
        shared_context={},
    )

    assert provider._session_store_key(sub) == "proj-1:1:relationship_review_agent"
