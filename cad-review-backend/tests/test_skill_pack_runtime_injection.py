from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.skill_pack_service",
        "services.task_planner_service",
        "services.audit_runtime.evidence_planner",
        "services.audit.relationship_discovery",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime") or name.startswith("services.audit.relationship_discovery"):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    skill_pack_service = importlib.import_module("services.skill_pack_service")
    task_planner_service = importlib.import_module("services.task_planner_service")
    evidence_planner = importlib.import_module("services.audit_runtime.evidence_planner")
    relationship_discovery = importlib.import_module("services.audit.relationship_discovery")
    database.init_db()
    return database, models, skill_pack_service, task_planner_service, evidence_planner, relationship_discovery


def test_skill_pack_changes_evidence_strategy(monkeypatch, tmp_path):
    database, models, skill_pack_service, _task_planner, evidence_planner, _relationship = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(
            models.AuditSkillEntry(
                skill_type="index",
                title="关系证据优先聚焦",
                content='{"evidence_bias":{"relationship":{"preferred_pack_type":"focus_pack"}}}',
                source="manual",
                execution_mode="ai",
                is_active=1,
                priority=1,
            )
        )
        db.commit()

        skill_profile = skill_pack_service.load_runtime_skill_profile(
            db,
            skill_type="index",
            stage_key="sheet_relationship_discovery",
        )
        plans = evidence_planner.plan_evidence_requests(
            task_type="relationship",
            source_sheet_no="A1.01",
            target_sheet_no="A4.01",
            skill_profile=skill_profile,
        )
    finally:
        db.close()

    assert plans[0].pack_type.value == "focus_pack"


def test_skill_pack_changes_task_priority(monkeypatch, tmp_path):
    database, models, _skill_pack_service, task_planner_service, _evidence_planner, _relationship = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-skill-priority", name="Skill Priority"))
        db.add_all(
            [
                models.SheetContext(
                    id="ctx-a101",
                    project_id="proj-skill-priority",
                    sheet_no="A1.01",
                    sheet_name="平面布置图",
                    status="ready",
                    meta_json='{"stats":{"indexes":1}}',
                ),
                models.SheetContext(
                    id="ctx-a401",
                    project_id="proj-skill-priority",
                    sheet_no="A4.01",
                    sheet_name="节点详图",
                    status="ready",
                    meta_json='{"stats":{"indexes":0}}',
                ),
                models.SheetEdge(
                    id="edge-a101-a401",
                    project_id="proj-skill-priority",
                    source_sheet_no="A1.01",
                    target_sheet_no="A4.01",
                    edge_type="index_ref",
                    confidence=1.0,
                    evidence_json='{"mention_count":2}',
                ),
                models.AuditSkillEntry(
                    skill_type="dimension",
                    title="尺寸任务前置",
                    content='{"task_bias":{"priority_offset":-1}}',
                    source="manual",
                    execution_mode="ai",
                    is_active=1,
                    priority=1,
                ),
            ]
        )
        db.commit()

        monkeypatch.setattr(task_planner_service, "plan_with_master_llm", lambda *args, **kwargs: {"ok": False, "reason": "disabled"})
        task_planner_service.build_audit_tasks("proj-skill-priority", 1, db)
        dim_task = (
            db.query(models.AuditTask)
            .filter(
                models.AuditTask.project_id == "proj-skill-priority",
                models.AuditTask.task_type == "dimension",
            )
            .first()
        )
    finally:
        db.close()

    assert dim_task is not None
    assert dim_task.priority == 1


def test_skill_pack_changes_worker_thresholds(monkeypatch, tmp_path):
    database, models, skill_pack_service, _task_planner, _evidence_planner, relationship_discovery = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(
            models.AuditSkillEntry(
                skill_type="index",
                title="关系置信度提高",
                content='{"judgement_policy":{"relationship":{"confidence_floor":0.9}}}',
                source="manual",
                execution_mode="ai",
                is_active=1,
                priority=1,
            )
        )
        db.commit()

        skill_profile = skill_pack_service.load_runtime_skill_profile(
            db,
            skill_type="index",
            stage_key="sheet_relationship_discovery",
        )
    finally:
        db.close()

    filtered = relationship_discovery.apply_relationship_runtime_policy(
        [
            {"source": "A1.01", "target": "A4.01", "confidence": 0.6},
            {"source": "A1.01", "target": "A4.02", "confidence": 0.95},
        ],
        skill_profile=skill_profile,
    )

    assert [item["target"] for item in filtered] == ["A4.02"]
