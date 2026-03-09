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
        "services.audit_runtime.orchestrator",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime"):
            sys.modules.pop(name, None)


def _load_orchestrator(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    database.init_db()
    return importlib.import_module("services.audit_runtime.orchestrator")


def test_execute_pipeline_keeps_legacy_path_when_flag_disabled(monkeypatch, tmp_path):
    orchestrator = _load_orchestrator(monkeypatch, tmp_path)
    calls: list[tuple[str, int, bool]] = []

    def _fake_legacy(project_id: str, audit_version: int, *, allow_incomplete: bool, clear_running):
        calls.append((project_id, audit_version, allow_incomplete))

    def _unexpected_v2(*args, **kwargs):
        raise AssertionError("v2 path should stay disabled")

    monkeypatch.delenv("AUDIT_ORCHESTRATOR_V2_ENABLED", raising=False)
    monkeypatch.setattr(orchestrator, "execute_pipeline_legacy", _fake_legacy)
    monkeypatch.setattr(orchestrator, "execute_pipeline_v2", _unexpected_v2)

    orchestrator.execute_pipeline("proj-legacy", 3, allow_incomplete=True, clear_running=lambda *_: None)

    assert calls == [("proj-legacy", 3, True)]


def test_execute_pipeline_switches_to_v2_path_when_flag_enabled(monkeypatch, tmp_path):
    orchestrator = _load_orchestrator(monkeypatch, tmp_path)
    calls: list[tuple[str, int, bool]] = []

    def _unexpected_legacy(*args, **kwargs):
        raise AssertionError("legacy path should not run when v2 is enabled")

    def _fake_v2(project_id: str, audit_version: int, *, allow_incomplete: bool, clear_running):
        calls.append((project_id, audit_version, allow_incomplete))

    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")
    monkeypatch.setattr(orchestrator, "execute_pipeline_legacy", _unexpected_legacy)
    monkeypatch.setattr(orchestrator, "execute_pipeline_v2", _fake_v2)

    orchestrator.execute_pipeline("proj-v2", 7, allow_incomplete=False, clear_running=lambda *_: None)

    assert calls == [("proj-v2", 7, False)]
