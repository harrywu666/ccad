from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.layout_json_service import backfill_layout_json, load_enriched_layout_json


def test_load_enriched_layout_json_does_not_backfill_implicitly(monkeypatch, tmp_path):
    project_dir = tmp_path / "projects" / "proj-preview"
    json_dir = project_dir / "jsons"
    dwg_dir = project_dir / "dwg"
    json_dir.mkdir(parents=True, exist_ok=True)
    dwg_dir.mkdir(parents=True, exist_ok=True)
    (dwg_dir / "source.dwg").write_text("stub", encoding="utf-8")

    source_json = json_dir / "source-refresh.json"
    source_json.write_text(
        json.dumps(
            {
                "source_dwg": "source.dwg",
                "layout_name": "A6.02a 卡座详图2",
                "sheet_no": "A6.02a",
                "layout_page_range": {"min": [0.0, 0.0], "max": [841.0, 594.0]},
                "model_range": {"min": [1.0, 1.0], "max": [2.0, 2.0]},
                "indexes": [
                    {"index_no": "3", "target_sheet": "A06.02b", "position": [541.48, 287.771], "source": "layout_space"}
                ],
                "title_blocks": [],
                "viewports": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import services.layout_json_service as layout_json_service

    monkeypatch.setattr(
        layout_json_service,
        "read_layout_indexes_from_dwg",
        lambda dwg_path, layout_name: [
            {
                "index_no": "3",
                "target_sheet": "A06.02b",
                "position": [539.182, 286.706],
                "insert_position": [541.48, 287.771],
                "anchor_source": "attribute_center",
            }
        ],
    )

    payload = load_enriched_layout_json(str(source_json))

    assert payload is not None
    assert payload["indexes"][0]["position"] == [541.48, 287.771]
    assert "insert_position" not in payload["indexes"][0]
    assert "anchor_source" not in payload["indexes"][0]

    original_json = json.loads(source_json.read_text(encoding="utf-8"))
    assert original_json["indexes"][0]["position"] == [541.48, 287.771]
    assert "insert_position" not in original_json["indexes"][0]
    assert "anchor_source" not in original_json["indexes"][0]


def test_backfill_layout_json_updates_legacy_index_visual_anchor(monkeypatch, tmp_path):
    project_dir = tmp_path / "projects" / "proj-preview"
    json_dir = project_dir / "jsons"
    dwg_dir = project_dir / "dwg"
    json_dir.mkdir(parents=True, exist_ok=True)
    dwg_dir.mkdir(parents=True, exist_ok=True)
    (dwg_dir / "source.dwg").write_text("stub", encoding="utf-8")

    source_json = json_dir / "source-refresh.json"
    source_json.write_text(
        json.dumps(
            {
                "source_dwg": "source.dwg",
                "layout_name": "A6.02a 卡座详图2",
                "sheet_no": "A6.02a",
                "layout_page_range": {"min": [0.0, 0.0], "max": [841.0, 594.0]},
                "model_range": {"min": [1.0, 1.0], "max": [2.0, 2.0]},
                "indexes": [
                    {"index_no": "3", "target_sheet": "A06.02b", "position": [541.48, 287.771], "source": "layout_space"}
                ],
                "title_blocks": [],
                "viewports": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import services.layout_json_service as layout_json_service

    monkeypatch.setattr(
        layout_json_service,
        "read_layout_indexes_from_dwg",
        lambda dwg_path, layout_name: [
            {
                "index_no": "3",
                "target_sheet": "A06.02b",
                "position": [539.182, 286.706],
                "insert_position": [541.48, 287.771],
                "anchor_source": "attribute_center",
            }
        ],
    )

    raw = backfill_layout_json(str(source_json))
    assert raw is not None

    payload = load_enriched_layout_json(str(source_json))
    assert payload is not None
    assert payload["indexes"][0]["position"] == [539.182, 286.706]
    assert payload["indexes"][0]["insert_position"] == [541.48, 287.771]
    assert payload["indexes"][0]["anchor_source"] == "attribute_center"
    assert payload["indexes"][0]["global_pct"] == {"x": 64.1, "y": 51.7}

    refreshed_json = json.loads(source_json.read_text(encoding="utf-8"))
    assert refreshed_json["indexes"][0]["position"] == [539.182, 286.706]
    assert refreshed_json["indexes"][0]["insert_position"] == [541.48, 287.771]
    assert refreshed_json["indexes"][0]["anchor_source"] == "attribute_center"


def test_backfill_layout_json_refreshes_stale_layout_page_range(monkeypatch, tmp_path):
    project_dir = tmp_path / "projects" / "proj-preview"
    json_dir = project_dir / "jsons"
    dwg_dir = project_dir / "dwg"
    json_dir.mkdir(parents=True, exist_ok=True)
    dwg_dir.mkdir(parents=True, exist_ok=True)
    (dwg_dir / "source.dwg").write_text("stub", encoding="utf-8")

    source_json = json_dir / "source-refresh.json"
    source_json.write_text(
        json.dumps(
            {
                "source_dwg": "source.dwg",
                "layout_name": "A1.11 厨房放大图",
                "layout_page_range": {"min": [-17.995, -17.985], "max": [823.005, 1170.815]},
                "indexes": [],
                "title_blocks": [],
                "viewports": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import services.layout_json_service as layout_json_service

    monkeypatch.setattr(
        layout_json_service,
        "read_layout_page_range_from_dwg",
        lambda dwg_path, layout_name: {"min": [0.0, 0.0], "max": [841.0, 594.0]},
    )
    monkeypatch.setattr(
        layout_json_service,
        "read_layout_indexes_from_dwg",
        lambda dwg_path, layout_name: [],
    )

    raw = backfill_layout_json(str(source_json))
    assert raw is not None
    assert raw["layout_page_range"] == {"min": [0.0, 0.0], "max": [841.0, 594.0]}

    refreshed_json = json.loads(source_json.read_text(encoding="utf-8"))
    assert refreshed_json["layout_page_range"] == {"min": [0.0, 0.0], "max": [841.0, 594.0]}


def test_backfill_layout_json_adds_detail_titles(monkeypatch, tmp_path):
    project_dir = tmp_path / "projects" / "proj-preview"
    json_dir = project_dir / "jsons"
    dwg_dir = project_dir / "dwg"
    json_dir.mkdir(parents=True, exist_ok=True)
    dwg_dir.mkdir(parents=True, exist_ok=True)
    (dwg_dir / "source.dwg").write_text("stub", encoding="utf-8")

    source_json = json_dir / "source-refresh.json"
    source_json.write_text(
        json.dumps(
            {
                "source_dwg": "source.dwg",
                "layout_name": "G0.04 门详图1",
                "sheet_no": "G0.04",
                "layout_page_range": {"min": [0.0, 0.0], "max": [841.0, 594.0]},
                "indexes": [],
                "title_blocks": [],
                "viewports": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import services.layout_json_service as layout_json_service

    monkeypatch.setattr(layout_json_service, "read_layout_indexes_from_dwg", lambda dwg_path, layout_name: [])
    monkeypatch.setattr(
        layout_json_service,
        "read_layout_detail_titles_from_dwg",
        lambda dwg_path, layout_name: [
            {
                "label": "A1",
                "title_lines": ["D01 前厅门", "DETAIL - LOBBY DOOR"],
                "title_text": "D01 前厅门 DETAIL - LOBBY DOOR",
                "block_name": "DET_TITLE",
                "layer": "G-ANNO-TITL",
                "attrs": [{"tag": "DN", "value": "A1"}],
                "position": [120.0, 60.0],
                "source": "model_space",
            }
        ],
    )

    raw = backfill_layout_json(str(source_json))
    assert raw is not None

    payload = load_enriched_layout_json(str(source_json))
    assert payload is not None
    assert payload["detail_titles"][0]["label"] == "A1"
    assert payload["detail_titles"][0]["source"] == "model_space"


def test_backfill_layout_json_adds_layout_fragments(monkeypatch, tmp_path):
    project_dir = tmp_path / "projects" / "proj-preview"
    json_dir = project_dir / "jsons"
    dwg_dir = project_dir / "dwg"
    json_dir.mkdir(parents=True, exist_ok=True)
    dwg_dir.mkdir(parents=True, exist_ok=True)
    (dwg_dir / "source.dwg").write_text("stub", encoding="utf-8")

    source_json = json_dir / "source-fragment.json"
    source_json.write_text(
        json.dumps(
            {
                "source_dwg": "source.dwg",
                "layout_name": "布局1",
                "sheet_no": "",
                "sheet_name": "",
                "layout_page_range": {"min": [0.0, 0.0], "max": [841.0, 594.0]},
                "indexes": [],
                "title_blocks": [],
                "viewports": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import services.layout_json_service as layout_json_service

    monkeypatch.setattr(layout_json_service, "read_layout_indexes_from_dwg", lambda dwg_path, layout_name: [])
    monkeypatch.setattr(layout_json_service, "read_layout_detail_titles_from_dwg", lambda dwg_path, layout_name: [])
    monkeypatch.setattr(
        layout_json_service,
        "read_layout_structure_from_dwg",
        lambda dwg_path, layout_name: {
            "sheet_no": "PL-01",
            "sheet_name": "平面图",
            "layout_frames": [
                {
                    "frame_id": "frame-1",
                    "frame_bbox": {"min": [10.0, 10.0], "max": [400.0, 280.0]},
                    "paper_size_hint": "A3",
                    "orientation": "landscape",
                    "confidence": 1.0,
                }
            ],
            "layout_fragments": [
                {
                    "fragment_id": "frame-1-fragment-1",
                    "frame_id": "frame-1",
                    "layout_name": "布局1",
                    "fragment_bbox": {"min": [10.0, 10.0], "max": [400.0, 280.0]},
                    "sheet_no": "PL-01",
                    "sheet_name": "平面图",
                    "title_blocks": [],
                    "detail_titles": [],
                    "indexes": [],
                    "dimensions": [],
                    "materials": [],
                    "viewports": [],
                    "fragment_confidence": 1.0,
                }
            ],
            "is_multi_sheet_layout": False,
        },
    )

    raw = backfill_layout_json(str(source_json))
    assert raw is not None
    assert raw["sheet_no"] == "PL-01"
    assert raw["sheet_name"] == "平面图"
    assert len(raw["layout_frames"]) == 1
    assert len(raw["layout_fragments"]) == 1
    assert raw["is_multi_sheet_layout"] is False
