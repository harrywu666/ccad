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
        "services.chief_review_memory_service",
        "services.audit_runtime.project_memory_store",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime.project_memory_store"):
            sys.modules.pop(name, None)


def _load_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()
    return database.SessionLocal, models


def test_project_memory_persists_hypothesis_pool(monkeypatch, tmp_path):
    session_local, models = _load_backend(monkeypatch, tmp_path)
    memory_service = importlib.import_module("services.chief_review_memory_service")

    db = session_local()
    try:
        db.add(models.Project(id="proj-memory", name="Memory Project"))
        db.commit()

        payload = {
            "sheet_graph_version": "v1",
            "active_hypotheses": [{"topic": "标高一致性"}],
            "resolved_hypotheses": [],
        }
        saved = memory_service.save_project_memory(
            db,
            project_id="proj-memory",
            audit_version=2,
            payload=payload,
        )
        loaded = memory_service.load_project_memory(
            db,
            project_id="proj-memory",
            audit_version=2,
        )

        assert saved["active_hypotheses"][0]["topic"] == "标高一致性"
        assert loaded["active_hypotheses"][0]["topic"] == "标高一致性"
    finally:
        db.close()
