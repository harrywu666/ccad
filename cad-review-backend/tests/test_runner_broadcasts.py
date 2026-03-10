from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_broadcasts import build_runner_broadcast_message
from services.audit_runtime.agent_reports import DimensionAgentReport
from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest


def _build_request() -> RunnerTurnRequest:
    return RunnerTurnRequest(
        agent_key="relationship_review_agent",
        agent_name="关系审查Agent",
        step_key="relationship_discovery",
        progress_hint=15,
        turn_kind="relationship_candidate_review",
        system_prompt="sys",
        user_prompt="user",
        meta={
            "candidate_index": 15,
            "candidate_total": 24,
            "source_sheet_no": "A-15",
            "target_sheet_no": "A-16",
        },
    )


def _build_subsession() -> RunnerSubsession:
    return RunnerSubsession(
        project_id="proj-runner-broadcast",
        audit_version=1,
        agent_key="relationship_review_agent",
        session_key="proj-runner-broadcast:1:relationship_review_agent",
        shared_context={},
    )


def test_runner_broadcast_summarizes_provider_state_into_plain_language():
    message = build_runner_broadcast_message(
        _build_request(),
        _build_subsession(),
        state="progress",
    )

    assert "正在复核第 15 组候选关系" in message


def test_runner_broadcast_covers_waiting_repair_retry_and_deferred_states():
    request = _build_request()
    subsession = _build_subsession()

    waiting = build_runner_broadcast_message(request, subsession, state="waiting")
    repairing = build_runner_broadcast_message(request, subsession, state="repairing")
    retrying = build_runner_broadcast_message(request, subsession, state="retrying")
    deferred = build_runner_broadcast_message(request, subsession, state="deferred")

    assert "分析时间较长" in waiting
    assert "正在自动整理" in repairing
    assert "正在重试" in retrying
    assert "先记下并继续处理" in deferred


def test_runner_broadcast_hides_internal_dimension_report_raw_details():
    from services.audit_runtime.runner_broadcasts import build_runner_broadcast_from_agent_report

    message = build_runner_broadcast_from_agent_report(
        "尺寸审查Agent",
        DimensionAgentReport(
            batch_summary="第 2 批尺寸关系结果不稳",
            blocking_issues=[{"kind": "unstable_output", "stage": "pair_compare"}],
            runner_help_request="restart_subsession",
            agent_confidence=0.35,
            next_recommended_action="rerun_current_batch",
        ),
    )

    assert "这批结果有点不稳" in message
    assert "unstable_output" not in message
