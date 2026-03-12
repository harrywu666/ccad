from __future__ import annotations

import asyncio
import importlib
import sys
from types import SimpleNamespace
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_dimension_skill_uses_agent_skill_prompt(monkeypatch):
    dimension_skill = importlib.import_module("services.audit_runtime.worker_skills.dimension_consistency_skill")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _Issue:
        def __init__(self):
            self.project_id = "proj-dim-skill"
            self.audit_version = 1
            self.type = "dimension"
            self.severity = "warning"
            self.sheet_no_a = "A1.01"
            self.sheet_no_b = "A4.01"
            self.location = "1/A1.01"
            self.description = "尺寸不一致"
            self.evidence_json = "{}"
            self.confidence = 0.88
            self.finding_status = "confirmed"
            self.review_round = 2
            self.rule_id = "dimension_pair_compare"
            self.evidence_pack_id = "paired_overview_pack"

    captured: dict[str, object] = {}

    async def fake_collect(*args, **kwargs):  # noqa: ANN001
        sheet_bundle = kwargs["sheet_prompt_bundle_builder"](
            {"sheet_no": "A1.01", "sheet_name": "首层平面图", "prompt": "单图提示", "visual_only": False},
            "dimension_single_sheet",
        )
        pair_bundle = kwargs["pair_prompt_bundle_builder"](
            {
                "a_sheet_no": "A1.01",
                "a_sheet_name": "首层平面图",
                "b_sheet_no": "A4.01",
                "b_sheet_name": "节点详图",
                "semantic_a": [],
                "semantic_b": [],
            }
        )
        captured["sheet_prompt_source"] = sheet_bundle.meta["prompt_source"]
        captured["pair_prompt_source"] = pair_bundle.meta["prompt_source"]
        captured["sheet_system_prompt"] = sheet_bundle.system_prompt
        captured["pair_system_prompt"] = pair_bundle.system_prompt
        return [_Issue()]

    monkeypatch.setattr(dimension_skill, "_collect_dimension_pair_issues_async", fake_collect)
    monkeypatch.setattr(
        dimension_skill,
        "_dimension_issue_evidence",
        lambda issue: {
            "sheet_no": issue.sheet_no_a,
            "location": issue.location,
            "rule_id": issue.rule_id,
            "evidence_pack_id": issue.evidence_pack_id,
            "description": issue.description,
            "severity": issue.severity,
        },
    )

    result = asyncio.run(
        dimension_skill.run_dimension_consistency_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-dim-skill",
                hypothesis_id="hyp-dim-skill",
                worker_kind="elevation_consistency",
                objective="核对 A1.01 与 A4.01",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-dim-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert captured["sheet_prompt_source"] == "agent_skill"
    assert captured["pair_prompt_source"] == "agent_skill"
    assert "Review Worker Agent" in str(captured["sheet_system_prompt"])
    assert "Elevation Consistency Worker Skill" in str(captured["sheet_system_prompt"])
    assert result.meta["skill_id"] == "elevation_consistency"
    assert result.meta["prompt_source"] == "agent_skill"


def test_dimension_skill_returns_rejected_when_no_issues(monkeypatch):
    dimension_skill = importlib.import_module("services.audit_runtime.worker_skills.dimension_consistency_skill")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    async def fake_collect(*args, **kwargs):  # noqa: ANN001
        return []

    monkeypatch.setattr(dimension_skill, "_collect_dimension_pair_issues_async", fake_collect)

    result = asyncio.run(
        dimension_skill.run_dimension_consistency_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-dim-empty",
                hypothesis_id="hyp-dim-empty",
                worker_kind="spatial_consistency",
                objective="核对 A1.01 与 A4.01",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-dim-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert result.status == "rejected"
    assert result.meta["skill_id"] == "spatial_consistency"
    assert result.meta["prompt_source"] == "agent_skill"


def test_dimension_skill_prefetches_cross_sheet_evidence(monkeypatch):
    dimension_skill = importlib.import_module("services.audit_runtime.worker_skills.dimension_consistency_skill")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _Issue:
        def __init__(self):
            self.project_id = "proj-dim-prefetch"
            self.audit_version = 1
            self.type = "dimension"
            self.severity = "warning"
            self.sheet_no_a = "A1.01"
            self.sheet_no_b = "A4.01"
            self.location = "1/A1.01"
            self.description = "尺寸不一致"
            self.evidence_json = "{}"
            self.confidence = 0.88
            self.finding_status = "confirmed"
            self.review_round = 1
            self.rule_id = "dimension_pair_compare"
            self.evidence_pack_id = "paired_overview_pack"

    captured: dict[str, object] = {}

    async def fake_collect(*args, **kwargs):  # noqa: ANN001
        return [_Issue()]

    async def fake_prefetch_regions(*, requests, evidence_service=None):  # noqa: ANN001
        del evidence_service
        captured["prefetch_count"] = len(requests)
        captured["focus_hint"] = requests[0].focus_hint
        captured["pack_type"] = requests[0].pack_type.value
        return SimpleNamespace(total_request_count=len(requests), unique_request_count=len(requests), cache_hits=0)

    monkeypatch.setattr(dimension_skill, "_collect_dimension_pair_issues_async", fake_collect)
    monkeypatch.setattr(
        dimension_skill,
        "_dimension_issue_evidence",
        lambda issue: {
            "sheet_no": issue.sheet_no_a,
            "location": issue.location,
            "rule_id": issue.rule_id,
            "evidence_pack_id": issue.evidence_pack_id,
            "description": issue.description,
            "severity": issue.severity,
        },
    )
    monkeypatch.setattr(
        dimension_skill,
        "locate_across_sheets",
        lambda **kwargs: [
            SimpleNamespace(
                source_sheet_no=kwargs["source_sheet_no"],
                target_sheet_no=kwargs["target_sheet_nos"][0],
            )
        ],
    )
    monkeypatch.setattr(dimension_skill, "prefetch_regions", fake_prefetch_regions)

    result = asyncio.run(
        dimension_skill.run_dimension_consistency_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-dim-prefetch",
                hypothesis_id="hyp-dim-prefetch",
                worker_kind="elevation_consistency",
                objective="核对 A1.01 与 A4.01",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                anchor_hint={"label": "3.000 标高"},
                context={
                    "project_id": "proj-dim-prefetch",
                    "audit_version": 1,
                    "sheet_assets": {
                        "A1.01": {"sheet_no": "A1.01", "pdf_path": "/tmp/a101.pdf", "page_index": 0},
                        "A4.01": {"sheet_no": "A4.01", "pdf_path": "/tmp/a401.pdf", "page_index": 1},
                    },
                },
            ),
            db="db-session",
        )
    )

    assert captured["prefetch_count"] == 1
    assert captured["focus_hint"] == "3.000 标高"
    assert captured["pack_type"] == "paired_overview_pack"
    assert result.meta["cross_sheet_anchor_count"] == 1
    assert result.meta["prefetch_request_count"] == 1
    assert result.meta["cross_sheet_prefetch_status"] == "ready"
