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
        "services.audit_runtime_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime_service"):
            sys.modules.pop(name, None)


def _load_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()
    runtime = importlib.import_module("services.audit_runtime_service")
    return database, models, runtime


def test_restart_master_agent_async_starts_resume_worker_with_new_generation(monkeypatch, tmp_path):
    database, models, runtime = _load_runtime(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-master-runtime", name="Master Runtime", status="auditing"))
        db.add(
            models.AuditRun(
                project_id="proj-master-runtime",
                audit_version=5,
                status="running",
                current_step="规划审核任务图",
                progress=35,
                provider_mode="kimi_sdk",
                scope_mode="partial",
            )
        )
        db.commit()
    finally:
        db.close()

    captured = {}

    def _fake_start(project_id, audit_version, *, allow_incomplete=False, provider_mode=None, resume_existing=False, worker_generation=None):  # noqa: ANN001
        captured.update(
            {
                "project_id": project_id,
                "audit_version": audit_version,
                "allow_incomplete": allow_incomplete,
                "provider_mode": provider_mode,
                "resume_existing": resume_existing,
                "worker_generation": worker_generation,
            }
        )

    monkeypatch.setattr(runtime, "start_audit_async", _fake_start)
    monkeypatch.setattr(runtime, "bump_project_worker_generation", lambda project_id: 4)

    result = runtime.restart_master_agent_async("proj-master-runtime", 5)

    assert result["restarted"] is True
    assert result["generation"] == 4
    assert captured == {
        "project_id": "proj-master-runtime",
        "audit_version": 5,
        "allow_incomplete": True,
        "provider_mode": "kimi_sdk",
        "resume_existing": True,
        "worker_generation": 4,
    }
