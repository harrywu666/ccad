from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_execute_pipeline_uses_chief_review_path_when_feature_flag_enabled(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    monkeypatch.setenv("AUDIT_CHIEF_REVIEW_ENABLED", "1")
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "0")

    captured = {}

    def _capture(impl, *args, **kwargs):  # noqa: ANN001
        captured["impl"] = impl.__name__

    monkeypatch.setattr(orchestrator, "_invoke_pipeline_impl", _capture)

    orchestrator.execute_pipeline(
        "proj-chief",
        1,
        clear_running=lambda project_id: None,
    )

    assert captured["impl"] == "execute_pipeline_chief_review"


def test_build_default_hypotheses_skips_memory_false_positives_and_resolved():
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")

    sheet_graph = SimpleNamespace(
        sheet_types={
            "A4-01": "detail",
            "A8-01": "reference",
            "A3-01": "elevation",
        },
        linked_targets={"A1-01": ["A4-01", "A8-01", "A3-01"]},
        node_hosts={},
    )

    hypotheses = orchestrator._build_default_hypotheses(
        sheet_graph,
        memory={
            "active_hypotheses": [],
            "false_positive_hints": [
                {
                    "source_sheet_no": "A1.01",
                    "target_sheet_nos": ["A8.01"],
                    "worker_kind": "index_reference",
                }
            ],
            "resolved_hypotheses": [
                {
                    "source_sheet_no": "A1.01",
                    "target_sheet_nos": ["A3.01"],
                    "worker_kind": "elevation_consistency",
                }
            ],
        },
    )

    assert len(hypotheses) == 1
    assert hypotheses[0]["topic"] == "节点归属复核"
    assert hypotheses[0]["context"]["suggested_worker_kind"] == "node_host_binding"


def test_build_default_hypotheses_keeps_escalated_active_hypothesis_priority():
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")

    sheet_graph = SimpleNamespace(
        sheet_types={"A4-01": "detail"},
        linked_targets={"A1-01": ["A4-01"]},
        node_hosts={},
    )

    hypotheses = orchestrator._build_default_hypotheses(
        sheet_graph,
        memory={
            "active_hypotheses": [
                {
                    "id": "hyp-existing",
                    "topic": "旧节点归属复核",
                    "objective": "旧目标",
                    "source_sheet_no": "A1.01",
                    "target_sheet_nos": ["A4.01"],
                    "priority": 0.91,
                    "context": {
                        "suggested_worker_kind": "node_host_binding",
                        "needs_chief_review": True,
                    },
                }
            ],
            "false_positive_hints": [],
            "resolved_hypotheses": [],
        },
    )

    assert hypotheses[0]["id"] == "hyp-existing"
    assert hypotheses[0]["priority"] >= 0.98
    assert hypotheses[0]["context"]["needs_chief_review"] is True


def test_update_chief_review_memory_learns_false_positive_and_keeps_escalation():
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")
    finding_schema = importlib.import_module("services.audit_runtime.finding_schema")

    memory = {
        "active_hypotheses": [
            {
                "id": "hyp-fp",
                "topic": "索引引用复核",
                "objective": "复核索引",
                "source_sheet_no": "A1.01",
                "target_sheet_nos": ["A8.01"],
                "context": {"suggested_worker_kind": "index_reference"},
            },
            {
                "id": "hyp-escalated",
                "topic": "节点归属复核",
                "objective": "复核节点归属",
                "source_sheet_no": "A1.01",
                "target_sheet_nos": ["A4.01"],
                "context": {"suggested_worker_kind": "node_host_binding"},
            },
            {
                "id": "hyp-confirmed",
                "topic": "标高一致性",
                "objective": "核对标高",
                "source_sheet_no": "A1.01",
                "target_sheet_nos": ["A3.01"],
                "context": {"suggested_worker_kind": "elevation_consistency"},
            },
        ],
        "resolved_hypotheses": [],
        "false_positive_hints": [],
    }

    updated = orchestrator._update_chief_review_memory(
        memory,
        worker_results=[
            review_task_schema.WorkerResultCard(
                task_id="task-fp",
                hypothesis_id="hyp-fp",
                worker_kind="index_reference",
                status="rejected",
                confidence=0.82,
                summary="索引不成立",
            ),
            review_task_schema.WorkerResultCard(
                task_id="task-escalated",
                hypothesis_id="hyp-escalated",
                worker_kind="node_host_binding",
                status="needs_review",
                confidence=0.52,
                summary="需要主审复核",
                escalate_to_chief=True,
            ),
            review_task_schema.WorkerResultCard(
                task_id="task-confirmed",
                hypothesis_id="hyp-confirmed",
                worker_kind="elevation_consistency",
                status="confirmed",
                confidence=0.91,
                summary="标高不一致",
            ),
        ],
        findings=[
            finding_schema.Finding(
                sheet_no="A1.01",
                location="A1.01 -> A3.01",
                rule_id="ELEV-001",
                finding_type="dim_mismatch",
                severity="warning",
                status="confirmed",
                confidence=0.91,
                source_agent="chief_review_agent",
                evidence_pack_id="chief_review_pack",
                review_round=1,
                triggered_by="hyp-confirmed",
                description="标高不一致",
            )
        ],
        escalations=[{"hypothesis_id": "hyp-escalated", "reasons": ["needs_review"]}],
    )

    assert updated["active_hypotheses"] == []
    assert [item["id"] for item in updated["chief_recheck_queue"]] == ["hyp-escalated"]
    assert updated["chief_recheck_queue"][0]["context"]["needs_chief_review"] is True
    assert updated["false_positive_hints"][0]["worker_kind"] == "index_reference"
    assert updated["resolved_hypotheses"][0]["worker_kind"] == "elevation_consistency"


def test_build_chief_sheet_graph_passes_semantic_runner(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    sheet_graph_builder = importlib.import_module("services.audit_runtime.sheet_graph_builder")

    captured = {}

    def fake_build_sheet_graph(*, sheet_contexts, sheet_edges, llm_runner=None):  # noqa: ANN001
        captured["llm_runner"] = llm_runner
        return SimpleNamespace(
            sheet_types={"A1-01": "plan"},
            linked_targets={},
            node_hosts={},
        )

    monkeypatch.setattr(sheet_graph_builder, "build_sheet_graph", fake_build_sheet_graph)

    graph = orchestrator._build_chief_sheet_graph(
        project_id="proj-chief",
        audit_version=21,
        sheet_contexts=[],
        sheet_edges=[],
    )

    assert graph.sheet_types["A1-01"] == "plan"
    assert callable(captured["llm_runner"])


def test_orchestrator_dispatches_incrementally_instead_of_single_bulk_batch():
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    chief_review_session = importlib.import_module("services.audit_runtime.chief_review_session")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    session = chief_review_session.ChiefReviewSession(project_id="proj-chief", audit_version=8)
    assignments = [
        review_task_schema.ReviewAssignment(
            assignment_id=f"assignment-{index}",
            review_intent="elevation_consistency",
            source_sheet_no="A1.06",
            target_sheet_nos=[f"A2.0{index}"],
            task_title=f"A1.06 -> A2.0{index}",
            acceptance_criteria=["核对标高"],
            expected_evidence_types=["anchors"],
            priority=0.9,
            dispatch_reason="chief_dispatch",
        )
        for index in range(1, 4)
    ]
    captured: list[str] = []

    async def _fake_worker_runner(task):
        captured.append(str(task.context.get("assignment_id")))
        return review_task_schema.WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="confirmed",
            confidence=0.88,
            summary=f"{task.id} ok",
        )

    worker_results = asyncio.run(
        orchestrator._dispatch_review_assignments_incrementally(
            chief_session=session,
            assignments=assignments,
            worker_runner=_fake_worker_runner,
        )
    )

    assert captured == ["assignment-1", "assignment-2", "assignment-3"]
    assert len(worker_results) == 3


def test_orchestrator_routes_worker_result_through_final_review_before_accepting(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
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
    result = review_task_schema.WorkerResultCard(
        task_id="asg-1",
        hypothesis_id="hyp-1",
        worker_kind="elevation_consistency",
        status="confirmed",
        confidence=0.91,
        summary="标高不一致",
        markdown_conclusion="## 任务结论\n- 标高不一致",
        evidence_bundle={
            "assignment_id": "asg-1",
            "grounding_status": "grounded",
            "anchors": [
                {
                    "sheet_no": "A1.06",
                    "role": "source",
                    "global_pct": {"x": 42.1, "y": 61.2},
                }
            ],
            "evidence_pack_id": "paired_overview_pack",
        },
        meta={"assignment_id": "asg-1"},
    )
    captured = {"final_review_called": False}

    def fake_run_final_review_agent(*, assignment, worker_result):  # noqa: ANN001
        captured["final_review_called"] = True
        return SimpleNamespace(
            decision="accepted",
            rationale="grounded",
            source_assignment_id=assignment.assignment_id,
            evidence_pack_id="paired_overview_pack",
            requires_grounding=True,
        )

    monkeypatch.setattr(orchestrator, "run_final_review_agent", fake_run_final_review_agent)

    accepted, escalations, decisions, redispatch_assignments = orchestrator._route_worker_results_through_final_review(
        assignments=[assignment],
        worker_results=[result],
    )

    assert captured["final_review_called"] is True
    assert len(accepted) == 1
    assert escalations == []
    assert len(decisions) == 1
    assert redispatch_assignments == []


def test_orchestrator_routes_redispatch_decision_back_to_chief_dispatch(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    chief_review_session = importlib.import_module("services.audit_runtime.chief_review_session")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    session = chief_review_session.ChiefReviewSession(project_id="proj-chief", audit_version=8)
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
    result = review_task_schema.WorkerResultCard(
        task_id="asg-1",
        hypothesis_id="hyp-1",
        worker_kind="elevation_consistency",
        status="needs_review",
        confidence=0.52,
        summary="证据不足",
        markdown_conclusion="## 任务结论\n- 证据不足",
        evidence_bundle={
            "assignment_id": "asg-1",
            "grounding_status": "weak",
            "anchors": [{"sheet_no": "A1.06", "role": "source"}],
            "evidence_pack_id": "paired_overview_pack",
        },
        meta={"assignment_id": "asg-1"},
    )
    captured = {"redispatches": 0, "chief_dispatch_called_again": False}

    def fake_run_final_review_agent(*, assignment, worker_result):  # noqa: ANN001
        return SimpleNamespace(
            decision="redispatch",
            rationale="请补充更强的定位证据",
            source_assignment_id=assignment.assignment_id,
            evidence_pack_id="paired_overview_pack",
            requires_grounding=True,
        )

    def fake_plan_assignments(memory):  # noqa: ANN001
        captured["chief_dispatch_called_again"] = True
        return [assignment]

    monkeypatch.setattr(orchestrator, "run_final_review_agent", fake_run_final_review_agent)
    monkeypatch.setattr(session, "plan_assignments", fake_plan_assignments)

    accepted, escalations, decisions, redispatch_assignments = orchestrator._route_worker_results_through_final_review(
        assignments=[assignment],
        worker_results=[result],
        chief_session=session,
        memory={"active_hypotheses": []},
    )
    captured["redispatches"] = len(redispatch_assignments)

    assert captured["redispatches"] == 1
    assert captured["chief_dispatch_called_again"] is True
    assert accepted == []
    assert escalations[0]["reasons"] == ["redispatch"]
