from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    for name in list(sys.modules):
        if name in {"database", "models"}:
            sys.modules.pop(name, None)


def _load_db(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()
    return database, models


def test_init_db_cleans_removed_codex_provider_history(monkeypatch, tmp_path):
    database, models = _load_db(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-cleanup", name="Cleanup Project"))
        db.add(
            models.AuditRun(
                project_id="proj-cleanup",
                audit_version=1,
                status="done",
                provider_mode="codex_sdk",
            )
        )
        db.add(
            models.AuditRunEvent(
                project_id="proj-cleanup",
                audit_version=1,
                event_kind="runner_turn_started",
                message="turn started",
                meta_json=json.dumps(
                    {
                        "provider_name": "codex_sdk",
                        "provider_mode": "codex_sdk",
                        "requested_provider_mode": "codex_sdk",
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
    finally:
        db.close()

    database.init_db()

    db = database.SessionLocal()
    try:
        run = db.query(models.AuditRun).filter_by(project_id="proj-cleanup", audit_version=1).one()
        event = db.query(models.AuditRunEvent).filter_by(project_id="proj-cleanup", audit_version=1).one()
        meta = json.loads(event.meta_json or "{}")
    finally:
        db.close()

    assert run.provider_mode == "kimi_sdk"
    assert meta["provider_name"] == "sdk"
    assert meta["provider_mode"] == "kimi_sdk"
    assert meta["requested_provider_mode"] == "kimi_sdk"


def test_init_db_skips_invalid_event_meta_json(monkeypatch, tmp_path):
    database, models = _load_db(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-bad-meta", name="Bad Meta Project"))
        db.add(
            models.AuditRunEvent(
                project_id="proj-bad-meta",
                audit_version=1,
                event_kind="runner_turn_started",
                message="bad meta",
                meta_json='{"provider_name":"codex_sdk"',
            )
        )
        db.commit()
    finally:
        db.close()

    database.init_db()

    db = database.SessionLocal()
    try:
        event = db.query(models.AuditRunEvent).filter_by(project_id="proj-bad-meta", audit_version=1).one()
    finally:
        db.close()

    assert event.meta_json == '{"provider_name":"codex_sdk"'
