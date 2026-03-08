from __future__ import annotations

import importlib
import io
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
        "services.drawing_ingest.dwg_ingest_service",
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


def test_upload_dwg_route_delegates_to_ingest_service(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-dwg-upload", name="DWG Upload Project", status="matching"))
        db.commit()
    finally:
        db.close()

    captured = {}

    async def fake_ingest(project_id, project, files, db, set_progress):  # noqa: ANN001
        captured["project_id"] = project_id
        captured["project_name"] = project.name
        captured["filenames"] = [f.filename for f in files]
        set_progress(project_id, "processing", 50, "fake-progress")
        return {
            "success": True,
            "summary": {
                "dwg_files": 1,
                "layouts_total": 2,
                "matched": 2,
                "unmatched": 0,
                "skipped_extra_layouts": 0,
                "placeholder_layouts": 0,
            },
            "results": [
                {
                    "dwg": "demo.dwg",
                    "layout_name": "布局1",
                    "sheet_no": "PL-01",
                    "sheet_name": "平面布置图",
                    "status": "matched",
                    "catalog_id": None,
                    "match_score": 1.0,
                    "json_id": "json-1",
                    "json_path": "/tmp/demo.json",
                    "data_version": 1,
                }
            ],
        }

    ingest_module = importlib.import_module("services.drawing_ingest.dwg_ingest_service")
    monkeypatch.setattr(ingest_module, "ingest_dwg_upload", fake_ingest)

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-dwg-upload/dwg/upload",
            files=[("files", ("demo.dwg", io.BytesIO(b"dwg-bytes"), "application/octet-stream"))],
        )
        progress = client.get("/api/projects/proj-dwg-upload/dwg/upload-progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["summary"]["matched"] == 2
    assert captured == {
        "project_id": "proj-dwg-upload",
        "project_name": "DWG Upload Project",
        "filenames": ["demo.dwg"],
    }
    assert progress.status_code == 200
    assert progress.json()["phase"] == "processing"
