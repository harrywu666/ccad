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
        "services.feedback_agent_prompt_asset_service",
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


def test_get_feedback_agent_prompts_returns_three_assets(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)
    settings = importlib.import_module("routers.settings")

    monkeypatch.setattr(
        settings,
        "list_feedback_agent_prompt_assets",
        lambda: {
            "items": [
                {"key": "prompt", "title": "误报反馈 Prompt", "description": "desc", "file_name": "PROMPT.md", "content": "prompt content"},
                {"key": "agent", "title": "误报反馈 AGENT.md", "description": "desc", "file_name": "AGENT.md", "content": "agent content"},
                {"key": "soul", "title": "误报反馈 SOUL.md", "description": "desc", "file_name": "SOUL.md", "content": "soul content"},
            ],
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/settings/feedback-agent-prompts")

    assert response.status_code == 200
    payload = response.json()
    assert [item["key"] for item in payload["items"]] == ["prompt", "agent", "soul"]


def test_update_feedback_agent_prompts_round_trip(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)
    settings = importlib.import_module("routers.settings")

    def _fake_update(items):
        assert items == [
            {"key": "prompt", "content": "new prompt"},
            {"key": "agent", "content": "new agent"},
        ]
        return {
            "items": [
                {"key": "prompt", "title": "误报反馈 Prompt", "description": "desc", "file_name": "PROMPT.md", "content": "new prompt"},
                {"key": "agent", "title": "误报反馈 AGENT.md", "description": "desc", "file_name": "AGENT.md", "content": "new agent"},
                {"key": "soul", "title": "误报反馈 SOUL.md", "description": "desc", "file_name": "SOUL.md", "content": "old soul"},
            ],
        }

    monkeypatch.setattr(settings, "update_feedback_agent_prompt_assets", _fake_update)

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/feedback-agent-prompts",
            json={
                "items": [
                    {"key": "prompt", "content": "new prompt"},
                    {"key": "agent", "content": "new agent"},
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["content"] == "new prompt"
    assert payload["items"][1]["content"] == "new agent"
