from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_modules() -> None:
    targets = (
        'database',
        'models',
        'services.master_planner_service',
    )
    for name in list(sys.modules):
        if name in targets:
            sys.modules.pop(name, None)


def test_master_planner_uses_codex_provider_when_selected(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('CCAD_DB_PATH', str(tmp_path / 'test.sqlite'))
    _clear_modules()

    database = importlib.import_module('database')
    models = importlib.import_module('models')
    service = importlib.import_module('services.master_planner_service')
    database.init_db()

    db = database.SessionLocal()
    try:
      db.add(models.AuditRun(project_id='proj-master-codex', audit_version=3, status='running', provider_mode='codex_sdk'))
      db.commit()
    finally:
      db.close()

    runner = service._get_master_runner('proj-master-codex', 3)

    assert runner.provider.provider_name == 'codex_sdk'
