from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_node_host_binding_skill_uses_agent_skill_prompt(monkeypatch):
    node_skill = importlib.import_module("services.audit_runtime.worker_skills.node_host_binding_skill")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    captured: dict[str, object] = {}

    monkeypatch.setattr(node_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(node_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        node_skill,
        "_load_ready_sheets",
        lambda project_id, db, sheet_filters=None: [
            {"sheet_no": "A1-01", "sheet_name": "首层平面图", "pdf_path": "/tmp/a.pdf", "page_index": 0},
            {"sheet_no": "A4-01", "sheet_name": "节点详图", "pdf_path": "/tmp/b.pdf", "page_index": 0},
        ],
    )
    monkeypatch.setattr(node_skill, "get_evidence_service", lambda: "fake-evidence-service")
    monkeypatch.setattr(node_skill, "_validate_and_normalize", lambda rels, valid_sheet_nos: rels)

    async def fake_discover_relationship_task_v2(**kwargs):  # noqa: ANN001
        prompt_bundle = kwargs["prompt_bundle"]
        captured["prompt_source"] = prompt_bundle.meta["prompt_source"]
        captured["system_prompt"] = prompt_bundle.system_prompt
        captured["user_prompt"] = prompt_bundle.user_prompt
        return [
            {
                "source": "A1.01",
                "target": "A4.01",
                "confidence": 0.93,
                "finding": {
                    "sheet_no": "A1.01",
                    "location": "A1.01 -> A4.01",
                    "rule_id": "relationship_visual_review",
                    "evidence_pack_id": "paired_overview_pack",
                    "description": "节点索引明确指向 A4.01",
                    "severity": "warning",
                },
            }
        ]

    monkeypatch.setattr(node_skill, "_discover_relationship_task_v2", fake_discover_relationship_task_v2)

    result = asyncio.run(
        node_skill.run_node_host_binding_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-node-skill",
                hypothesis_id="hyp-node-skill",
                worker_kind="node_host_binding",
                objective="确认节点归属",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-node-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert captured["prompt_source"] == "agent_skill"
    assert "Review Worker Agent" in str(captured["system_prompt"])
    assert "Node Host Binding Worker Skill" in str(captured["system_prompt"])
    assert "A1-01" in str(captured["user_prompt"])
    assert result.meta["skill_id"] == "node_host_binding"
    assert result.meta["prompt_source"] == "agent_skill"
    assert result.meta["issue_count"] == 1


def test_node_host_binding_skill_prefetches_cross_sheet_evidence(monkeypatch):
    node_skill = importlib.import_module("services.audit_runtime.worker_skills.node_host_binding_skill")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    captured: dict[str, object] = {}
    fake_evidence_service = object()

    monkeypatch.setattr(node_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(node_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        node_skill,
        "_load_ready_sheets",
        lambda project_id, db, sheet_filters=None: [
            {"sheet_no": "A1-01", "sheet_name": "首层平面图", "pdf_path": "/tmp/a.pdf", "page_index": 0},
            {"sheet_no": "A4-01", "sheet_name": "节点详图", "pdf_path": "/tmp/b.pdf", "page_index": 1},
        ],
    )
    monkeypatch.setattr(node_skill, "get_evidence_service", lambda: fake_evidence_service)
    monkeypatch.setattr(node_skill, "_validate_and_normalize", lambda rels, valid_sheet_nos: rels)
    monkeypatch.setattr(
        node_skill,
        "locate_across_sheets",
        lambda **kwargs: [
            SimpleNamespace(
                source_sheet_no=kwargs["source_sheet_no"],
                target_sheet_no=kwargs["target_sheet_nos"][0],
            )
        ],
    )

    async def fake_prefetch_regions(*, requests, evidence_service=None):  # noqa: ANN001
        captured["prefetch_count"] = len(requests)
        captured["prefetch_pack_type"] = requests[0].pack_type.value
        captured["prefetch_service"] = evidence_service
        return SimpleNamespace(total_request_count=len(requests), unique_request_count=len(requests), cache_hits=0)

    async def fake_discover_relationship_task_v2(**kwargs):  # noqa: ANN001
        captured["discover_evidence_service"] = kwargs["evidence_service"]
        return [
            {
                "source": "A1.01",
                "target": "A4.01",
                "confidence": 0.93,
                "finding": {
                    "sheet_no": "A1.01",
                    "location": "A1.01 -> A4.01",
                    "rule_id": "relationship_visual_review",
                    "evidence_pack_id": "paired_overview_pack",
                    "description": "节点索引明确指向 A4.01",
                    "severity": "warning",
                },
            }
        ]

    monkeypatch.setattr(node_skill, "prefetch_regions", fake_prefetch_regions)
    monkeypatch.setattr(node_skill, "_discover_relationship_task_v2", fake_discover_relationship_task_v2)

    result = asyncio.run(
        node_skill.run_node_host_binding_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-node-prefetch",
                hypothesis_id="hyp-node-prefetch",
                worker_kind="node_host_binding",
                objective="确认节点归属",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                anchor_hint={"label": "节点 D1"},
                context={"project_id": "proj-node-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert captured["prefetch_count"] == 1
    assert captured["prefetch_pack_type"] == "paired_overview_pack"
    assert captured["prefetch_service"] is fake_evidence_service
    assert captured["discover_evidence_service"] is fake_evidence_service
    assert result.meta["cross_sheet_anchor_count"] == 1
    assert result.meta["prefetch_request_count"] == 1
    assert result.meta["cross_sheet_prefetch_status"] == "ready"


def test_node_host_binding_skill_passes_assignment_meta_into_runtime_prompt(monkeypatch):
    node_skill = importlib.import_module("services.audit_runtime.worker_skills.node_host_binding_skill")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    captured: dict[str, object] = {}

    monkeypatch.setattr(node_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(node_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        node_skill,
        "_load_ready_sheets",
        lambda project_id, db, sheet_filters=None: [
            {"sheet_no": "A1-01", "sheet_name": "首层平面图", "pdf_path": "/tmp/a.pdf", "page_index": 0},
            {"sheet_no": "A4-01", "sheet_name": "节点详图", "pdf_path": "/tmp/b.pdf", "page_index": 0},
        ],
    )
    monkeypatch.setattr(node_skill, "get_evidence_service", lambda: "fake-evidence-service")
    monkeypatch.setattr(node_skill, "_validate_and_normalize", lambda rels, valid_sheet_nos: rels)

    async def fake_discover_relationship_task_v2(**kwargs):  # noqa: ANN001
        prompt_bundle = kwargs["prompt_bundle"]
        captured["assignment_id"] = prompt_bundle.meta.get("assignment_id")
        captured["visible_session_key"] = prompt_bundle.meta.get("visible_session_key")
        return []

    monkeypatch.setattr(node_skill, "_discover_relationship_task_v2", fake_discover_relationship_task_v2)

    asyncio.run(
        node_skill.run_node_host_binding_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-node-assignment-meta",
                hypothesis_id="hyp-node-assignment-meta",
                worker_kind="node_host_binding",
                objective="确认节点归属",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={
                    "project_id": "proj-node-assignment-meta",
                    "audit_version": 1,
                    "assignment_id": "asg-node-1",
                },
            ),
            db="db-session",
        )
    )

    assert captured["assignment_id"] == "asg-node-1"
    assert captured["visible_session_key"] == "assignment:asg-node-1"


def test_node_host_binding_skill_returns_markdown_conclusion_and_evidence_bundle(monkeypatch):
    node_skill = importlib.import_module("services.audit_runtime.worker_skills.node_host_binding_skill")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    monkeypatch.setattr(node_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(node_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        node_skill,
        "_load_ready_sheets",
        lambda project_id, db, sheet_filters=None: [
            {"sheet_no": "A1-01", "sheet_name": "首层平面图", "pdf_path": "/tmp/a.pdf", "page_index": 0},
            {"sheet_no": "A4-01", "sheet_name": "节点详图", "pdf_path": "/tmp/b.pdf", "page_index": 0},
        ],
    )
    monkeypatch.setattr(node_skill, "get_evidence_service", lambda: "fake-evidence-service")
    monkeypatch.setattr(node_skill, "_validate_and_normalize", lambda rels, valid_sheet_nos: rels)

    async def fake_discover_relationship_task_v2(**kwargs):  # noqa: ANN001
        return [
            {
                "source": "A1.01",
                "target": "A4.01",
                "confidence": 0.93,
                "source_anchor": {
                    "sheet_no": "A1.01",
                    "role": "source",
                    "global_pct": {"x": 12.0, "y": 40.0},
                },
                "finding": {
                    "sheet_no": "A1.01",
                    "location": "A1.01 -> A4.01",
                    "rule_id": "relationship_visual_review",
                    "evidence_pack_id": "paired_overview_pack",
                    "description": "节点索引明确指向 A4.01",
                    "severity": "warning",
                },
            }
        ]

    monkeypatch.setattr(node_skill, "_discover_relationship_task_v2", fake_discover_relationship_task_v2)

    result = asyncio.run(
        node_skill.run_node_host_binding_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-node-bundle",
                hypothesis_id="hyp-node-bundle",
                worker_kind="node_host_binding",
                objective="确认节点归属",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-node-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert result.markdown_conclusion.startswith("## 任务结论")
    assert result.evidence_bundle["grounding_status"] == "grounded"
    assert result.evidence_bundle["anchors"][0]["sheet_no"] == "A1.01"
