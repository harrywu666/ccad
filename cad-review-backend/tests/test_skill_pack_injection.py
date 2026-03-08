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
        "services.ai_prompt_service",
        "services.skill_pack_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services."):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    ai_prompt_service = importlib.import_module("services.ai_prompt_service")
    index_audit = importlib.import_module("services.audit.index_audit")
    material_audit = importlib.import_module("services.audit.material_audit")
    skill_pack_service = importlib.import_module("services.skill_pack_service")
    database.init_db()
    return database, models, ai_prompt_service, index_audit, material_audit, skill_pack_service


def test_resolve_stage_system_prompt_with_skills_appends_dimension_rules(monkeypatch, tmp_path):
    database, models, ai_prompt_service, _, _, _ = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(
            models.AuditSkillEntry(
                skill_type="dimension",
                title="门洞净宽一致性",
                content="门洞净宽与平面索引对应图应保持一致，发现冲突时优先提示。",
                source="manual",
                execution_mode="ai",
                stage_keys='["dimension_pair_compare"]',
                is_active=1,
                priority=1,
            )
        )
        db.commit()
    finally:
        db.close()

    prompt = ai_prompt_service.resolve_stage_system_prompt_with_skills(
        "dimension_pair_compare",
        "dimension",
    )

    assert "【审查知识库】" in prompt
    assert "门洞净宽一致性" in prompt
    assert "历史经验修正" not in prompt


def test_build_index_alias_map_parses_same_sheet_rule(monkeypatch, tmp_path):
    _, _, _, _, _, skill_pack_service = _load_modules(monkeypatch, tmp_path)

    alias_map = skill_pack_service.build_index_alias_map(
        [
            {
                "title": "图号等价",
                "content": "A06.00a 和 A6.00 应视为同一图号。",
            }
        ]
    )

    assert alias_map["A0600A"] == alias_map["A600"]


def test_index_audit_uses_alias_rules_to_match_target_sheet(monkeypatch, tmp_path):
    database, models, _, index_audit, _, _ = _load_modules(monkeypatch, tmp_path)
    source_json = tmp_path / "source.json"
    target_json = tmp_path / "target.json"
    source_json.write_text(
        '{"indexes":[{"index_no":"D1","target_sheet":"A06.00a","grid":"F11"}],"title_blocks":[]}',
        encoding="utf-8",
    )
    target_json.write_text(
        '{"indexes":[],"title_blocks":[{"title_label":"D1","attrs":[]}]}',
        encoding="utf-8",
    )

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-index-skill", name="Index Skill"))
        db.add_all(
            [
                models.JsonData(
                    id="json-source",
                    project_id="proj-index-skill",
                    sheet_no="A1.01",
                    json_path=str(source_json),
                    is_latest=1,
                ),
                models.JsonData(
                    id="json-target",
                    project_id="proj-index-skill",
                    sheet_no="A6.00",
                    json_path=str(target_json),
                    is_latest=1,
                ),
                models.AuditSkillEntry(
                    skill_type="index",
                    title="图号等价",
                    content="A06.00a 和 A6.00 应视为同一图号。",
                    source="manual",
                    execution_mode="code",
                    is_active=1,
                    priority=1,
                ),
            ]
        )
        db.commit()

        issues = index_audit.audit_indexes("proj-index-skill", 1, db)
        assert issues == []
    finally:
        db.close()


def test_index_audit_uses_detail_titles_to_match_target_sheet(monkeypatch, tmp_path):
    database, models, _, index_audit, _, _ = _load_modules(monkeypatch, tmp_path)
    source_json = tmp_path / "source.json"
    target_json = tmp_path / "target.json"
    source_json.write_text(
        '{"indexes":[{"index_no":"A1","target_sheet":"G0.04","grid":"F11"}],"title_blocks":[]}',
        encoding="utf-8",
    )
    target_json.write_text(
        (
            '{"indexes":[],"title_blocks":[],"detail_titles":'
            '[{"label":"A1","title_lines":["D01 前厅门","DETAIL - LOBBY DOOR"],"source":"model_space"}]}'
        ),
        encoding="utf-8",
    )

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-index-detail-title", name="Index Detail Title"))
        db.add_all(
            [
                models.JsonData(
                    id="json-source-detail-title",
                    project_id="proj-index-detail-title",
                    sheet_no="G0.03",
                    json_path=str(source_json),
                    is_latest=1,
                ),
                models.JsonData(
                    id="json-target-detail-title",
                    project_id="proj-index-detail-title",
                    sheet_no="G0.04",
                    json_path=str(target_json),
                    is_latest=1,
                ),
            ]
        )
        db.commit()

        issues = index_audit.audit_indexes("proj-index-detail-title", 1, db)
        assert issues == []
    finally:
        db.close()


def test_material_audit_uses_ai_review_hook(monkeypatch, tmp_path):
    database, models, _, _, material_audit, _ = _load_modules(monkeypatch, tmp_path)
    material_json = tmp_path / "material.json"
    material_json.write_text(
        (
            '{"material_table":[{"code":"M01","name":"白色乳胶漆"}],'
            '"materials":[{"code":"M01","name":"白色艺术涂料","grid":"C3"}]}'
        ),
        encoding="utf-8",
    )

    async def fake_ai_review(**_: object):
        return [
            {
                "severity": "warning",
                "location": "材料编号M01",
                "material_code": "M01",
                "description": "图中材料与材料表名称语义不一致，请人工复核。",
                "evidence": {"code": "M01", "grid": "C3", "why": "同编号但材料语义不同"},
            }
        ]

    monkeypatch.setattr(material_audit, "_run_material_ai_review", fake_ai_review)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-material-skill", name="Material Skill"))
        db.add(
            models.JsonData(
                id="json-material",
                project_id="proj-material-skill",
                sheet_no="A2.01",
                json_path=str(material_json),
                is_latest=1,
            )
        )
        db.commit()

        issues = material_audit.audit_materials("proj-material-skill", 1, db)
        descriptions = [issue.description for issue in issues]
        assert "图中材料与材料表名称语义不一致，请人工复核。" in descriptions
    finally:
        db.close()


def test_build_audit_tasks_falls_back_to_rule_based_when_master_planner_times_out(monkeypatch, tmp_path):
    database, models, _, _, _, _ = _load_modules(monkeypatch, tmp_path)
    import services.task_planner_service as task_planner_service

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-planner-timeout", name="Planner Timeout"))
        db.add(
            models.SheetContext(
                id="ctx-a101",
                project_id="proj-planner-timeout",
                sheet_no="A1.01",
                sheet_name="平面布置图",
                status="ready",
                meta_json='{"stats":{"indexes":2}}',
            )
        )
        db.add(
            models.SheetContext(
                id="ctx-a401",
                project_id="proj-planner-timeout",
                sheet_no="A4.01",
                sheet_name="节点详图",
                status="ready",
                meta_json='{"stats":{"indexes":0}}',
            )
        )
        db.add(
            models.SheetEdge(
                id="edge-a101-a401",
                project_id="proj-planner-timeout",
                source_sheet_no="A1.01",
                target_sheet_no="A4.01",
                edge_type="index_ref",
                confidence=1.0,
                evidence_json='{"mention_count": 2}',
            )
        )
        db.commit()

        monkeypatch.setattr(
            task_planner_service,
            "plan_with_master_llm",
            lambda project_id, contexts, edges: {"ok": False, "reason": "llm_timeout"},
        )

        summary = task_planner_service.build_audit_tasks("proj-planner-timeout", 1, db)
        tasks = db.query(models.AuditTask).filter(models.AuditTask.project_id == "proj-planner-timeout").all()
    finally:
        db.close()

    assert summary["total"] == 3
    assert sorted((task.task_type, task.source_sheet_no, task.target_sheet_no or "") for task in tasks) == [
        ("dimension", "A1.01", "A4.01"),
        ("index", "A1.01", ""),
        ("material", "A1.01", "A4.01"),
    ]
