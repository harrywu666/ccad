from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_index_reference_skill_uses_skill_bundle_and_returns_worker_result(monkeypatch):
    index_skill = importlib.import_module("services.audit_runtime.worker_skills.index_reference_skill")
    index_audit = importlib.import_module("services.audit.index_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _Issue:
        def __init__(self):
            self.project_id = "proj-index-skill"
            self.audit_version = 1
            self.type = "index"
            self.severity = "warning"
            self.sheet_no_a = "A1.01"
            self.sheet_no_b = "A4.01"
            self.location = "索引D1"
            self.description = "目标图里未找到同编号索引"
            self.evidence_json = "{}"
            self.confidence = 0.87
            self.finding_status = "confirmed"
            self.review_round = 2

    captured: dict[str, object] = {}

    monkeypatch.setattr(index_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(index_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(index_audit, "load_active_skill_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(index_audit, "build_index_alias_map", lambda *args, **kwargs: {})

    def fake_collect(*args, **kwargs):  # noqa: ANN001
        captured["source_sheet_filters"] = kwargs.get("source_sheet_filters")
        captured["target_sheet_filters"] = kwargs.get("target_sheet_filters")
        return [{"issue": _Issue(), "review_kind": "missing_target_index_no"}]

    monkeypatch.setattr(index_audit, "_collect_index_issue_candidates", fake_collect)
    monkeypatch.setattr(index_audit, "_index_ai_review_enabled", lambda: False)
    monkeypatch.setattr(index_audit, "_review_index_issue_candidates_async", lambda *args, **kwargs: [])
    monkeypatch.setattr(index_audit, "_reviewable_index_issue", lambda kind: True)
    monkeypatch.setattr(index_audit, "_apply_index_finding", lambda issue, candidate: issue)
    monkeypatch.setattr(
        index_audit,
        "_index_issue_evidence",
        lambda issue: {
            "sheet_no": issue.sheet_no_a,
            "location": issue.location,
            "rule_id": "index_visual_review",
            "evidence_pack_id": "overview_pack",
            "description": issue.description,
            "severity": issue.severity,
        },
    )

    result = asyncio.run(
        index_skill.run_index_reference_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-index-skill",
                hypothesis_id="hyp-index-skill",
                worker_kind="index_reference",
                objective="确认索引引用",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-index-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert captured["source_sheet_filters"] == ["A1.01"]
    assert captured["target_sheet_filters"] == ["A4.01"]
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "index_reference"
    assert result.meta["skill_path"].endswith("agents/review_worker/skills/index_reference/SKILL.md")


def test_index_reference_skill_returns_rejected_when_no_candidates(monkeypatch):
    index_skill = importlib.import_module("services.audit_runtime.worker_skills.index_reference_skill")
    index_audit = importlib.import_module("services.audit.index_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    monkeypatch.setattr(index_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(index_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(index_audit, "load_active_skill_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(index_audit, "build_index_alias_map", lambda *args, **kwargs: {})
    monkeypatch.setattr(index_audit, "_collect_index_issue_candidates", lambda *args, **kwargs: [])

    result = asyncio.run(
        index_skill.run_index_reference_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-index-empty",
                hypothesis_id="hyp-index-empty",
                worker_kind="index_reference",
                objective="确认索引引用",
                source_sheet_no="A1.01",
                target_sheet_nos=["A4.01"],
                context={"project_id": "proj-index-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert result.status == "rejected"
    assert result.meta["skill_id"] == "index_reference"
