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
        "services.review_worker_skill_asset_service",
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


def test_get_review_worker_skill_assets_returns_skill_items(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)
    settings = importlib.import_module("routers.settings")

    monkeypatch.setattr(
        settings,
        "list_review_worker_skill_assets",
        lambda: {
            "items": [
                {"key": "node_host_binding", "title": "节点归属 Skill", "description": "desc", "file_name": "SKILL.md", "content": "node body"},
                {"key": "index_reference", "title": "索引引用 Skill", "description": "desc", "file_name": "SKILL.md", "content": "index body"},
                {"key": "material_semantic_consistency", "title": "材料语义一致性 Skill", "description": "desc", "file_name": "SKILL.md", "content": "material body"},
                {"key": "elevation_consistency", "title": "标高一致性 Skill", "description": "desc", "file_name": "SKILL.md", "content": "elevation body"},
                {"key": "spatial_consistency", "title": "空间一致性 Skill", "description": "desc", "file_name": "SKILL.md", "content": "spatial body"},
            ],
        },
    )

    with TestClient(app) as client:
        response = client.get("/api/settings/review-worker-skills")

    assert response.status_code == 200
    payload = response.json()
    assert [item["key"] for item in payload["items"]] == [
        "node_host_binding",
        "index_reference",
        "material_semantic_consistency",
        "elevation_consistency",
        "spatial_consistency",
    ]


def test_update_review_worker_skill_assets_round_trip(monkeypatch, tmp_path):
    app = _load_test_app(monkeypatch, tmp_path)
    settings = importlib.import_module("routers.settings")

    def _fake_update(items):
        assert items == [
            {"key": "index_reference", "content": "new index skill"},
        ]
        return {
            "items": [
                {"key": "node_host_binding", "title": "节点归属 Skill", "description": "desc", "file_name": "SKILL.md", "content": "old node skill"},
                {"key": "index_reference", "title": "索引引用 Skill", "description": "desc", "file_name": "SKILL.md", "content": "new index skill"},
                {"key": "material_semantic_consistency", "title": "材料语义一致性 Skill", "description": "desc", "file_name": "SKILL.md", "content": "old material skill"},
                {"key": "elevation_consistency", "title": "标高一致性 Skill", "description": "desc", "file_name": "SKILL.md", "content": "old elevation skill"},
                {"key": "spatial_consistency", "title": "空间一致性 Skill", "description": "desc", "file_name": "SKILL.md", "content": "old spatial skill"},
            ],
        }

    monkeypatch.setattr(settings, "update_review_worker_skill_assets", _fake_update)

    with TestClient(app) as client:
        response = client.put(
            "/api/settings/review-worker-skills",
            json={
                "items": [
                    {"key": "index_reference", "content": "new index skill"},
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    index_item = next(item for item in payload["items"] if item["key"] == "index_reference")
    assert index_item["content"] == "new index skill"
