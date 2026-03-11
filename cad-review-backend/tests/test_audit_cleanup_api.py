from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "main",
        "routers.audit",
        "routers.projects",
        "routers.categories",
        "routers.catalog",
        "routers.drawings",
        "routers.dwg",
        "routers.report",
        "routers.settings",
        "routers.feedback",
        "routers.skill_pack",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def test_delete_audit_version_cleans_up_orphan_runtime_records(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-cleanup", name="Cleanup Project", status="done"))
        db.add(models.AuditRun(project_id="proj-cleanup", audit_version=3, status="done"))
        db.add(models.AuditResult(
            id="result-1",
            project_id="proj-cleanup",
            audit_version=3,
            type="index",
            severity="warning",
        ))
        db.add(models.AuditTask(
            id="task-1",
            project_id="proj-cleanup",
            audit_version=3,
            task_type="index",
            priority=1,
            status="done",
        ))
        db.add(models.AuditRunEvent(
            project_id="proj-cleanup",
            audit_version=3,
            level="info",
            message="旧日志",
        ))
        db.add(models.FeedbackSample(
            id="feedback-1",
            project_id="proj-cleanup",
            audit_result_id="result-1",
            audit_version=3,
            issue_type="index",
        ))
        db.add(models.Drawing(id="drawing-1", project_id="proj-cleanup", status="matched"))
        db.add(models.DrawingAnnotation(
            id="anno-1",
            drawing_id="drawing-1",
            project_id="proj-cleanup",
            audit_version=3,
            annotation_board="{}",
        ))
        db.add(models.AuditIssueDrawing(
            id="issue-drawing-1",
            project_id="proj-cleanup",
            audit_result_id="result-1",
            audit_version=3,
            match_side="source",
            drawing_id="drawing-1",
        ))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.delete("/api/projects/proj-cleanup/audit/version/3")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"]["events"] == 1
    assert payload["deleted"]["feedback_samples"] == 1
    assert payload["deleted"]["issue_drawings"] == 1
    assert payload["deleted"]["annotations"] == 1

    db = session_local()
    try:
        assert db.query(models.AuditRun).filter(models.AuditRun.project_id == "proj-cleanup").count() == 0
        assert db.query(models.AuditResult).filter(models.AuditResult.project_id == "proj-cleanup").count() == 0
        assert db.query(models.AuditTask).filter(models.AuditTask.project_id == "proj-cleanup").count() == 0
        assert db.query(models.AuditRunEvent).filter(models.AuditRunEvent.project_id == "proj-cleanup").count() == 0
        assert db.query(models.FeedbackSample).filter(models.FeedbackSample.project_id == "proj-cleanup").count() == 0
        assert db.query(models.AuditIssueDrawing).filter(models.AuditIssueDrawing.project_id == "proj-cleanup").count() == 0
        assert db.query(models.DrawingAnnotation).filter(models.DrawingAnnotation.project_id == "proj-cleanup").count() == 0
    finally:
        db.close()


def test_delete_audit_version_deletes_event_only_versions_instead_of_404(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-event-only", name="Event Only Project", status="ready"))
        db.add(models.AuditRunEvent(
            project_id="proj-event-only",
            audit_version=7,
            level="info",
            message="孤儿日志",
        ))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.delete("/api/projects/proj-event-only/audit/version/7")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"]["events"] == 1


def test_stop_audit_force_cleans_current_version_records_and_artifacts(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    storage = importlib.import_module("services.storage_path_service")
    project_dir = tmp_path / "project-files"
    cache_dir = project_dir / "cache" / "dimension-v1"
    reports_dir = project_dir / "reports"
    annotated_dir = reports_dir / "annotated_v4"
    cache_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir.mkdir(parents=True, exist_ok=True)

    for file_name in ("cache-a.json", "cache-b.json"):
        (cache_dir / file_name).write_text("{}", encoding="utf-8")
    for file_name in (
        "report_v4.pdf",
        "report_v4.xlsx",
        "report_v4_marked.pdf",
        "report_v4_anchors.json",
    ):
        (reports_dir / file_name).write_text("temp", encoding="utf-8")
    (annotated_dir / "page-1.png").write_text("temp", encoding="utf-8")

    monkeypatch.setattr(storage, "resolve_project_dir", lambda project, ensure=False: project_dir)

    db = session_local()
    try:
        db.add(models.Project(id="proj-stop-cleanup", name="Stop Cleanup Project", status="auditing"))
        db.add(models.Catalog(
            id="stop-catalog-1",
            project_id="proj-stop-cleanup",
            sheet_no="A-01",
            sheet_name="平面图",
            status="locked",
        ))
        db.add(models.AuditRun(project_id="proj-stop-cleanup", audit_version=4, status="running"))
        db.add(models.AuditResult(
            id="stop-result-1",
            project_id="proj-stop-cleanup",
            audit_version=4,
            type="index",
            severity="warning",
        ))
        db.add(models.AuditTask(
            id="stop-task-1",
            project_id="proj-stop-cleanup",
            audit_version=4,
            task_type="index",
            priority=1,
            status="running",
        ))
        db.add(models.AuditRunEvent(
            project_id="proj-stop-cleanup",
            audit_version=4,
            level="info",
            message="正在执行",
        ))
        db.add(models.FeedbackSample(
            id="stop-feedback-1",
            project_id="proj-stop-cleanup",
            audit_result_id="stop-result-1",
            audit_version=4,
            issue_type="index",
        ))
        db.add(models.Drawing(
            id="stop-drawing-1",
            project_id="proj-stop-cleanup",
            catalog_id="stop-catalog-1",
            sheet_no="A-01",
            status="matched",
        ))
        db.add(models.JsonData(
            id="stop-json-1",
            project_id="proj-stop-cleanup",
            catalog_id="stop-catalog-1",
            sheet_no="A-01",
            json_path=str(tmp_path / "a-01.json"),
            is_latest=1,
            status="matched",
        ))
        db.add(models.DrawingAnnotation(
            id="stop-anno-1",
            drawing_id="stop-drawing-1",
            project_id="proj-stop-cleanup",
            audit_version=4,
            annotation_board="{}",
        ))
        db.add(models.AuditIssueDrawing(
            id="stop-issue-drawing-1",
            project_id="proj-stop-cleanup",
            audit_result_id="stop-result-1",
            audit_version=4,
            match_side="source",
            drawing_id="stop-drawing-1",
        ))
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.post("/api/projects/proj-stop-cleanup/audit/stop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["audit_version"] == 4
    assert payload["deleted"]["results"] == 1
    assert payload["deleted"]["runs"] == 1
    assert payload["deleted"]["tasks"] == 1
    assert payload["deleted"]["events"] == 1
    assert payload["deleted"]["feedback_samples"] == 1
    assert payload["deleted"]["issue_drawings"] == 1
    assert payload["deleted"]["annotations"] == 1
    assert payload["artifacts"]["cache_files"] == 2
    assert payload["artifacts"]["report_files"] == 5

    db = session_local()
    try:
        project = db.query(models.Project).filter(models.Project.id == "proj-stop-cleanup").first()
        assert project is not None
        assert project.status == "ready"
        assert project.cache_version == 1
        assert db.query(models.AuditRun).filter(models.AuditRun.project_id == "proj-stop-cleanup").count() == 0
        assert db.query(models.AuditResult).filter(models.AuditResult.project_id == "proj-stop-cleanup").count() == 0
        assert db.query(models.AuditTask).filter(models.AuditTask.project_id == "proj-stop-cleanup").count() == 0
        assert db.query(models.AuditRunEvent).filter(models.AuditRunEvent.project_id == "proj-stop-cleanup").count() == 0
        assert db.query(models.FeedbackSample).filter(models.FeedbackSample.project_id == "proj-stop-cleanup").count() == 0
        assert db.query(models.AuditIssueDrawing).filter(models.AuditIssueDrawing.project_id == "proj-stop-cleanup").count() == 0
        assert db.query(models.DrawingAnnotation).filter(models.DrawingAnnotation.project_id == "proj-stop-cleanup").count() == 0
    finally:
        db.close()

    assert not any(cache_dir.glob("*.json"))
    assert not (reports_dir / "report_v4.pdf").exists()
    assert not (reports_dir / "report_v4.xlsx").exists()
    assert not (reports_dir / "report_v4_marked.pdf").exists()
    assert not (reports_dir / "report_v4_anchors.json").exists()
    assert not annotated_dir.exists()
