from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_final_review_rejects_worker_conclusion_without_grounding():
    final_review_agent = importlib.import_module("services.audit_runtime.final_review_agent")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    assignment = review_task_schema.ReviewAssignment(
        assignment_id="asg-1",
        review_intent="elevation_consistency",
        source_sheet_no="A1.06",
        target_sheet_nos=["A2.00"],
        task_title="A1.06 -> A2.00",
        acceptance_criteria=["核对标高"],
        expected_evidence_types=["anchors"],
        priority=0.9,
        dispatch_reason="chief_dispatch",
    )
    worker_result = review_task_schema.WorkerResultCard(
        task_id="asg-1",
        hypothesis_id="hyp-1",
        worker_kind="elevation_consistency",
        status="confirmed",
        confidence=0.91,
        summary="标高不一致",
        markdown_conclusion="## 任务结论\n- 标高不一致",
        evidence_bundle={
            "assignment_id": "asg-1",
            "grounding_status": "missing",
            "anchors": [],
            "evidence_pack_id": "paired_overview_pack",
        },
        meta={"assignment_id": "asg-1"},
    )

    decision = final_review_agent.run_final_review_agent(
        assignment=assignment,
        worker_result=worker_result,
    )

    assert decision.decision == "needs_more_evidence"
    assert decision.decision_source == "rule_fallback"
    assert decision.source_assignment_id == "asg-1"


def test_final_review_rejects_relationship_signal_even_with_grounding():
    final_review_agent = importlib.import_module("services.audit_runtime.final_review_agent")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    assignment = review_task_schema.ReviewAssignment(
        assignment_id="asg-2",
        review_intent="node_host_binding",
        source_sheet_no="A1.01a",
        target_sheet_nos=["A6.02"],
        task_title="A1.01a -> A6.02",
        acceptance_criteria=["确认是否真是施工图问题"],
        expected_evidence_types=["anchors"],
        priority=0.8,
        dispatch_reason="chief_dispatch",
    )
    worker_result = review_task_schema.WorkerResultCard(
        task_id="asg-2",
        hypothesis_id="hyp-2",
        worker_kind="node_host_binding",
        status="confirmed",
        confidence=0.93,
        summary="圆圈内标记 A6.02",
        markdown_conclusion="## 任务结论\n- 这是关系线索，不是正式问题",
        evidence_bundle={
            "assignment_id": "asg-2",
            "result_kind": "relationship_signal",
            "grounding_status": "grounded",
            "anchors": [
                {
                    "sheet_no": "A1.01a",
                    "role": "source",
                    "global_pct": {"x": 12.0, "y": 40.0},
                }
            ],
            "evidence_pack_id": "paired_overview_pack",
        },
        meta={"assignment_id": "asg-2"},
    )

    decision = final_review_agent.run_final_review_agent(
        assignment=assignment,
        worker_result=worker_result,
    )

    assert decision.decision == "rejected"
    assert decision.decision_source == "rule_fallback"
    assert "关系线索" in decision.rationale


def test_final_review_prefers_llm_decision_when_enabled(monkeypatch):
    final_review_agent = importlib.import_module("services.audit_runtime.final_review_agent")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    monkeypatch.setenv("AUDIT_FINAL_REVIEW_LLM_MODE", "always")
    monkeypatch.setattr(
        final_review_agent,
        "_call_final_review_llm",
        lambda system_prompt, user_prompt: {
            "decision": "accepted",
            "rationale": "终审LLM认为证据和结论都满足通过条件",
            "requires_grounding": True,
        },
    )

    assignment = review_task_schema.ReviewAssignment(
        assignment_id="asg-llm-1",
        review_intent="elevation_consistency",
        source_sheet_no="A1.06",
        target_sheet_nos=["A2.00"],
        task_title="A1.06 -> A2.00",
        acceptance_criteria=["核对标高"],
        expected_evidence_types=["anchors"],
        priority=0.9,
        dispatch_reason="chief_dispatch",
    )
    worker_result = review_task_schema.WorkerResultCard(
        task_id="asg-llm-1",
        hypothesis_id="hyp-llm-1",
        worker_kind="elevation_consistency",
        status="confirmed",
        confidence=0.31,
        summary="标高可能不一致",
        markdown_conclusion="## 任务结论\n- 标高可能不一致",
        evidence_bundle={
            "assignment_id": "asg-llm-1",
            "result_kind": "issue",
            "grounding_status": "grounded",
            "anchors": [
                {
                    "sheet_no": "A1.06",
                    "role": "source",
                    "global_pct": {"x": 34.0, "y": 52.0},
                }
            ],
            "evidence_pack_id": "paired_overview_pack",
        },
        meta={"assignment_id": "asg-llm-1"},
    )

    decision = final_review_agent.run_final_review_agent(
        assignment=assignment,
        worker_result=worker_result,
    )

    assert decision.decision == "accepted"
    assert decision.decision_source == "llm"
    assert "终审LLM" in decision.rationale


def test_final_review_llm_cannot_bypass_grounding_guardrail(monkeypatch):
    final_review_agent = importlib.import_module("services.audit_runtime.final_review_agent")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    monkeypatch.setenv("AUDIT_FINAL_REVIEW_LLM_MODE", "always")
    monkeypatch.setattr(
        final_review_agent,
        "_call_final_review_llm",
        lambda system_prompt, user_prompt: {
            "decision": "accepted",
            "rationale": "终审LLM建议直接通过",
            "requires_grounding": True,
        },
    )

    assignment = review_task_schema.ReviewAssignment(
        assignment_id="asg-llm-2",
        review_intent="elevation_consistency",
        source_sheet_no="A1.06",
        target_sheet_nos=["A2.00"],
        task_title="A1.06 -> A2.00",
        acceptance_criteria=["核对标高"],
        expected_evidence_types=["anchors"],
        priority=0.9,
        dispatch_reason="chief_dispatch",
    )
    worker_result = review_task_schema.WorkerResultCard(
        task_id="asg-llm-2",
        hypothesis_id="hyp-llm-2",
        worker_kind="elevation_consistency",
        status="confirmed",
        confidence=0.95,
        summary="标高不一致",
        markdown_conclusion="## 任务结论\n- 标高不一致",
        evidence_bundle={
            "assignment_id": "asg-llm-2",
            "result_kind": "issue",
            "grounding_status": "missing",
            "anchors": [],
            "evidence_pack_id": "paired_overview_pack",
        },
        meta={"assignment_id": "asg-llm-2"},
    )

    decision = final_review_agent.run_final_review_agent(
        assignment=assignment,
        worker_result=worker_result,
    )

    assert decision.decision == "needs_more_evidence"
    assert decision.decision_source == "rule_fallback"
    assert "grounded anchors" in decision.rationale
