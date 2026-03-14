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


def test_get_agent_assets_returns_review_kernel_assets(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)
    settings = importlib.import_module("routers.settings")

    monkeypatch.setattr(
        settings,
        "get_agent_assets",
        lambda agent_id: {
            "agent_id": agent_id,
            "items": [
                {"key": "soul_core", "title": "SOUL.md", "description": "desc", "file_name": "SOUL.md", "content": "soul content"},
                {"key": "review_reporter_agent", "title": "AGENT_ReviewReporter.md", "description": "desc", "file_name": "AGENT_ReviewReporter.md", "content": "agent content"},
            ],
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/settings/agent-assets/review_kernel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == "review_kernel"
    assert [item["key"] for item in payload["items"]] == ["soul_core", "review_reporter_agent"]


def test_update_agent_assets_round_trip(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)
    settings = importlib.import_module("routers.settings")

    def _fake_update(agent_id, items):
        assert agent_id == "review_kernel"
        assert items == [
            {"key": "review_reporter_agent", "content": "new reporter"},
        ]
        return {
            "agent_id": agent_id,
            "items": [
                {"key": "review_reporter_agent", "title": "AGENT_ReviewReporter.md", "description": "desc", "file_name": "AGENT_ReviewReporter.md", "content": "new reporter"},
                {"key": "soul_core", "title": "SOUL.md", "description": "desc", "file_name": "SOUL.md", "content": "core soul"},
            ],
        }

    monkeypatch.setattr(settings, "update_agent_assets", _fake_update)

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/agent-assets/review_kernel",
            json={
                "items": [
                    {"key": "review_reporter_agent", "content": "new reporter"},
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["content"] == "new reporter"


def test_load_agent_runtime_bundle_uses_review_kernel_files(monkeypatch, tmp_path):
    _clear_backend_modules()
    agent_asset_service = importlib.import_module("services.agent_asset_service")

    root = tmp_path / "review_kernel"
    root.mkdir(parents=True)
    (root / "SOUL.md").write_text("# SOUL\ncore soul\n", encoding="utf-8")
    (root / "AGENT_PageClassifier.md").write_text("# AGENT\npage\n", encoding="utf-8")
    (root / "SOUL_DELTA_PageClassifier.md").write_text("# DELTA\npage\n", encoding="utf-8")
    (root / "AGENT_SemanticAugmentor.md").write_text("# AGENT\nsemantic\n", encoding="utf-8")
    (root / "SOUL_DELTA_SemanticAugmentor.md").write_text("# DELTA\nsemantic\n", encoding="utf-8")
    (root / "AGENT_ReviewReporter.md").write_text("# AGENT\nreporter\n", encoding="utf-8")
    (root / "SOUL_DELTA_ReviewReporter.md").write_text("# DELTA\nreporter\n", encoding="utf-8")
    (root / "AGENT_ReviewQA.md").write_text("# AGENT\nqa\n", encoding="utf-8")
    (root / "SOUL_DELTA_ReviewQA.md").write_text("# DELTA\nqa\n", encoding="utf-8")

    monkeypatch.setattr(agent_asset_service, "AGENTS_ROOT", root)

    bundle = agent_asset_service.load_agent_asset_bundle("review_kernel")
    assert "reporter" in bundle.agent_markdown
    assert "core soul" in bundle.soul_markdown
