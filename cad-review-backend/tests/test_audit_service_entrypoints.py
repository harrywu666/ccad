from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import services.audit_service as audit_service


def test_audit_service_dimension_entrypoint_delegates_to_modular_implementation(monkeypatch):
    captured: dict[str, object] = {}

    def fake_dimension_audit(project_id, audit_version, db, pair_filters=None):
        captured["project_id"] = project_id
        captured["audit_version"] = audit_version
        captured["db"] = db
        captured["pair_filters"] = pair_filters
        return ["dimension-ok"]

    module = importlib.import_module("services.audit.dimension_audit")
    monkeypatch.setattr(module, "audit_dimensions", fake_dimension_audit)

    result = audit_service.audit_dimensions("proj-1", 3, "db-session", [("A1.01", "A4.01")])

    assert result == ["dimension-ok"]
    assert captured == {
        "project_id": "proj-1",
        "audit_version": 3,
        "db": "db-session",
        "pair_filters": [("A1.01", "A4.01")],
    }


def test_audit_service_material_entrypoint_delegates_to_modular_implementation(monkeypatch):
    captured: dict[str, object] = {}

    def fake_material_audit(project_id, audit_version, db, sheet_filters=None):
        captured["project_id"] = project_id
        captured["audit_version"] = audit_version
        captured["db"] = db
        captured["sheet_filters"] = sheet_filters
        return ["material-ok"]

    module = importlib.import_module("services.audit.material_audit")
    monkeypatch.setattr(module, "audit_materials", fake_material_audit)

    result = audit_service.audit_materials("proj-2", 5, "db-session", ["A1.01"])

    assert result == ["material-ok"]
    assert captured == {
        "project_id": "proj-2",
        "audit_version": 5,
        "db": "db-session",
        "sheet_filters": ["A1.01"],
    }

