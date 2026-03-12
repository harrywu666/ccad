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
        "services.audit_runtime.state_transitions",
        "services.audit_runtime.orchestrator",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime"):
            sys.modules.pop(name, None)


def _load_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    state_transitions = importlib.import_module("services.audit_runtime.state_transitions")
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    database.init_db()
    return database.SessionLocal, models, state_transitions, orchestrator


def test_execute_pipeline_records_plain_language_events(monkeypatch, tmp_path):
    session_local, models, _state_transitions, orchestrator = _load_runtime(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-runtime-events", name="Runtime Events"))
        db.add(models.AuditRun(project_id="proj-runtime-events", audit_version=1, status="running"))
        db.add_all(
            [
                models.SheetContext(
                    id="ctx-1",
                    project_id="proj-runtime-events",
                    sheet_no="A1.01",
                    sheet_name="平面图",
                    status="ready",
                ),
                models.SheetContext(
                    id="ctx-2",
                    project_id="proj-runtime-events",
                    sheet_no="A2.01",
                    sheet_name="材料图",
                    status="ready",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(orchestrator, "clear_cancel_request", lambda project_id: None)
    monkeypatch.setattr(orchestrator, "match_three_lines", lambda project_id, db: {
        "summary": {"total": 2, "ready": 2, "missing_png": 0, "missing_json": 0, "missing_all": 0}
    })
    monkeypatch.setattr(
        orchestrator,
        "build_sheet_contexts",
        lambda project_id, db: {"ready_contexts": 2, "contexts_total": 2, "edges_total": 1},
    )
    monkeypatch.setattr(orchestrator, "discover_relationships", lambda project_id, db: [])
    monkeypatch.setattr(orchestrator, "save_ai_edges", lambda project_id, relationships, db: 0)
    monkeypatch.setattr(orchestrator, "build_audit_tasks", lambda project_id, audit_version, db: {
        "index_tasks": 0,
        "dimension_tasks": 0,
        "material_tasks": 0,
        "total_tasks": 0,
    })

    try:
        orchestrator.execute_pipeline("proj-runtime-events", 1, clear_running=lambda project_id: None)
    except RuntimeError:
        pass

    db = session_local()
    try:
        events = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-runtime-events",
                models.AuditRunEvent.audit_version == 1,
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    messages = [event.message for event in events]
    assert "主审 Agent 正在整理这次审图需要的基础数据" in messages
    assert "主审 Agent 已整理好基础数据，共 2 张图纸可进入审图" in messages
    assert "主审 Agent 已整理好图纸上下文，当前有 2 张图纸可继续分析" in messages
    assert "主审 Agent 已生成 0 张副审任务卡" in messages
    assert any("主审 Agent 已整理完成审核报告" in message for message in messages)
    assert all(event.agent_key for event in events)
    assert all(event.agent_name for event in events)
    assert all(event.event_kind for event in events)
    assert all(event.progress_hint is not None for event in events)
    assert events[0].agent_key == "chief_review_agent"
    assert events[0].agent_name == "主审 Agent"
    assert events[0].event_kind == "phase_started"
    metas = []
    for event in events:
        if event.meta_json:
            import json

            metas.append(json.loads(event.meta_json))
    assert any(meta.get("pipeline_mode") == "chief_review" for meta in metas)
    assert any(meta.get("planner_source") == "chief_agent" for meta in metas)
    assert any(meta.get("task_stage") == "worker_task_planning" for meta in metas)
