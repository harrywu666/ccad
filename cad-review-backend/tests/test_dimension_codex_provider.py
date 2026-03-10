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
        'services.audit.dimension_audit',
    )
    for name in list(sys.modules):
        if name in targets:
            sys.modules.pop(name, None)


def test_dimension_agent_uses_codex_provider_when_selected(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('CCAD_DB_PATH', str(tmp_path / 'test.sqlite'))
    _clear_modules()

    database = importlib.import_module('database')
    models = importlib.import_module('models')
    dimension_audit = importlib.import_module('services.audit.dimension_audit')
    database.init_db()

    db = database.SessionLocal()
    try:
      db.add(models.AuditRun(project_id='proj-dimension-codex', audit_version=4, status='running', provider_mode='codex_sdk'))
      db.commit()
    finally:
      db.close()

    runner = dimension_audit._get_dimension_runner(
      'proj-dimension-codex',
      4,
      call_kimi=lambda **kwargs: None,
    )

    assert runner.provider.provider_name == 'codex_sdk'
