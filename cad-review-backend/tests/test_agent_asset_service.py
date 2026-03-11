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
        "services.ai_prompt_service",
        "services.agent_asset_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    main = importlib.import_module("main")
    database.init_db()
    return main.app


def test_get_agent_assets_returns_three_assets(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)
    settings = importlib.import_module("routers.settings")

    monkeypatch.setattr(
        settings,
        "get_agent_assets",
        lambda agent_id: {
            "agent_id": agent_id,
            "items": [
                {"key": "agent", "title": "chief_review AGENTS.md", "description": "desc", "file_name": "AGENTS.md", "content": "agent content"},
                {"key": "soul", "title": "chief_review SOUL.md", "description": "desc", "file_name": "SOUL.md", "content": "soul content"},
                {"key": "memory", "title": "chief_review MEMORY.md", "description": "desc", "file_name": "MEMORY.md", "content": "memory content"},
            ],
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/settings/agent-assets/chief_review")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == "chief_review"
    assert [item["key"] for item in payload["items"]] == ["agent", "soul", "memory"]


def test_update_agent_assets_round_trip(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)
    settings = importlib.import_module("routers.settings")

    def _fake_update(agent_id, items):
        assert agent_id == "chief_review"
        assert items == [
            {"key": "agent", "content": "new agent"},
            {"key": "memory", "content": "new memory"},
        ]
        return {
            "agent_id": agent_id,
            "items": [
                {"key": "agent", "title": "chief_review AGENTS.md", "description": "desc", "file_name": "AGENTS.md", "content": "new agent"},
                {"key": "soul", "title": "chief_review SOUL.md", "description": "desc", "file_name": "SOUL.md", "content": "old soul"},
                {"key": "memory", "title": "chief_review MEMORY.md", "description": "desc", "file_name": "MEMORY.md", "content": "new memory"},
            ],
        }

    monkeypatch.setattr(settings, "update_agent_assets", _fake_update)

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/agent-assets/chief_review",
            json={
                "items": [
                    {"key": "agent", "content": "new agent"},
                    {"key": "memory", "content": "new memory"},
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["content"] == "new agent"
    assert payload["items"][2]["content"] == "new memory"


def test_build_agent_runtime_prompt_includes_agent_soul_memory(monkeypatch, tmp_path):
    _clear_backend_modules()
    agent_asset_service = importlib.import_module("services.agent_asset_service")
    ai_prompt_service = importlib.import_module("services.ai_prompt_service")

    root = tmp_path / "agents"
    agent_dir = root / "chief_review"
    agent_dir.mkdir(parents=True)
    (agent_dir / "AGENTS.md").write_text("# AGENT\nagent rules\n", encoding="utf-8")
    (agent_dir / "SOUL.md").write_text("# SOUL\nsoul rules\n", encoding="utf-8")
    (agent_dir / "MEMORY.md").write_text("# MEMORY\nmemory notes\n", encoding="utf-8")

    monkeypatch.setattr(agent_asset_service, "AGENTS_ROOT", root)

    prompt = ai_prompt_service.build_agent_runtime_prompt(
        "chief_review",
        extra_sections=["# EXTRA\nextra context"],
    )

    assert "# AGENT" in prompt
    assert "# SOUL" in prompt
    assert "# MEMORY" in prompt
    assert "# EXTRA" in prompt
