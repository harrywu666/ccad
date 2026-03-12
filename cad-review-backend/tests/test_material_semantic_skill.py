from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_material_skill_returns_worker_skill_metadata(monkeypatch):
    material_skill = importlib.import_module("services.audit_runtime.worker_skills.material_semantic_skill")
    material_audit = importlib.import_module("services.audit.material_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    class _Issue:
        def __init__(self):
            self.project_id = "proj-material-skill"
            self.audit_version = 1
            self.type = "material"
            self.severity = "warning"
            self.sheet_no_a = "A1.01"
            self.sheet_no_b = None
            self.location = "材料编号M01"
            self.description = "材料名称命名不一致"
            self.evidence_json = "{}"
            self.confidence = 0.83
            self.finding_status = "confirmed"
            self.review_round = 1

    captured: dict[str, object] = {}

    monkeypatch.setattr(material_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(material_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})

    def fake_collect(*args, **kwargs):  # noqa: ANN001
        captured["sheet_filters"] = kwargs.get("sheet_filters")
        return ([_Issue()], [])

    monkeypatch.setattr(material_audit, "_collect_material_rule_issues_and_ai_jobs", fake_collect)
    monkeypatch.setattr(material_audit, "_apply_material_finding", lambda issue: issue)
    monkeypatch.setattr(material_audit, "_run_material_ai_reviews_bounded", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        material_audit,
        "_material_issue_evidence",
        lambda issue: {
            "sheet_no": issue.sheet_no_a,
            "location": issue.location,
            "rule_id": "material_consistency_review",
            "evidence_pack_id": "focus_pack",
            "description": issue.description,
            "severity": issue.severity,
        },
    )

    result = asyncio.run(
        material_skill.run_material_semantic_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-material-skill",
                hypothesis_id="hyp-material-skill",
                worker_kind="material_semantic_consistency",
                objective="确认材料一致性",
                source_sheet_no="A1.01",
                target_sheet_nos=[],
                context={"project_id": "proj-material-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert captured["sheet_filters"] == ["A1.01"]
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "material_semantic_consistency"
    assert result.meta["skill_path"].endswith(
        "agents/review_worker/skills/material_semantic_consistency/SKILL.md"
    )


def test_material_skill_returns_rejected_when_no_issues(monkeypatch):
    material_skill = importlib.import_module("services.audit_runtime.worker_skills.material_semantic_skill")
    material_audit = importlib.import_module("services.audit.material_audit")
    review_task_schema = importlib.import_module("services.audit_runtime.review_task_schema")

    monkeypatch.setattr(material_skill, "load_runtime_skill_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(material_skill, "load_feedback_runtime_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(material_audit, "_collect_material_rule_issues_and_ai_jobs", lambda *args, **kwargs: ([], []))

    result = asyncio.run(
        material_skill.run_material_semantic_skill(
            task=review_task_schema.WorkerTaskCard(
                id="task-material-empty",
                hypothesis_id="hyp-material-empty",
                worker_kind="material_semantic_consistency",
                objective="确认材料一致性",
                source_sheet_no="A1.01",
                target_sheet_nos=[],
                context={"project_id": "proj-material-skill", "audit_version": 1},
            ),
            db="db-session",
        )
    )

    assert result.status == "rejected"
    assert result.meta["skill_id"] == "material_semantic_consistency"
