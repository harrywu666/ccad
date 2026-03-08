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
        "routers.settings",
        "routers.skill_pack",
        "services.ai_prompt_service",
        "services.skill_pack_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    _clear_backend_modules()

    database = importlib.import_module("database")
    main = importlib.import_module("main")
    database.init_db()
    return main.app


def test_get_skill_types_returns_execution_modes_and_stage_catalog(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/settings/skill-types")

    assert response.status_code == 200
    payload = response.json()
    assert [item["skill_type"] for item in payload["items"]] == [
        "index",
        "dimension",
        "material",
    ]
    dimension = next(item for item in payload["items"] if item["skill_type"] == "dimension")
    assert dimension["execution_mode"] == "ai"
    assert dimension["default_stage_keys"] == [
        "dimension_single_sheet",
        "dimension_pair_compare",
    ]
    assert {item["stage_key"] for item in dimension["allowed_stages"]} == {
        "dimension_single_sheet",
        "dimension_pair_compare",
    }


def test_skill_pack_crud_and_toggle_round_trip(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/settings/skill-packs",
            json={
                "skill_type": "dimension",
                "title": "核对门洞尺寸一致性",
                "content": "重点检查门洞净宽与两图表达是否一致。",
                "priority": 5,
                "stage_keys": ["dimension_pair_compare"],
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()["item"]
        assert created["skill_type"] == "dimension"
        assert created["is_active"] is True

        toggle_response = client.post(
            f"/api/settings/skill-packs/{created['id']}/toggle",
            json={"is_active": False},
        )
        assert toggle_response.status_code == 200
        assert toggle_response.json()["item"]["is_active"] is False

        list_response = client.get("/api/settings/skill-packs")
        assert list_response.status_code == 200
        items = list_response.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "核对门洞尺寸一致性"
        assert items[0]["stage_keys"] == ["dimension_pair_compare"]
        assert items[0]["is_active"] is False
