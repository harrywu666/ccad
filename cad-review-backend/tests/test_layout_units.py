from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.drawing_ingest.layout_units import expand_layout_json_units


def test_expand_layout_json_units_returns_fragment_units_when_multiple_fragments_have_identity():
    json_info = {
        "layout_name": "布局1",
        "sheet_no": "",
        "sheet_name": "",
        "data": {
            "layout_name": "布局1",
            "sheet_no": "",
            "sheet_name": "",
            "scale": "1:50",
            "layers": [{"name": "A"}],
            "layout_frames": [
                {"frame_id": "f1", "frame_bbox": {"min": [0, 0], "max": [100, 100]}},
                {"frame_id": "f2", "frame_bbox": {"min": [120, 0], "max": [220, 100]}},
            ],
            "layout_fragments": [
                {
                    "fragment_id": "frag-1",
                    "frame_id": "f1",
                    "fragment_bbox": {"min": [0, 0], "max": [100, 100]},
                    "sheet_no": "PL-01",
                    "sheet_name": "平面图",
                    "title_blocks": [],
                    "detail_titles": [],
                    "indexes": [],
                    "dimensions": [{"id": "d1"}],
                    "materials": [],
                    "viewports": [],
                },
                {
                    "fragment_id": "frag-2",
                    "frame_id": "f2",
                    "fragment_bbox": {"min": [120, 0], "max": [220, 100]},
                    "sheet_no": "EL-01",
                    "sheet_name": "立面图",
                    "title_blocks": [],
                    "detail_titles": [],
                    "indexes": [],
                    "dimensions": [{"id": "d2"}],
                    "materials": [],
                    "viewports": [],
                },
            ],
            "is_multi_sheet_layout": True,
        },
    }

    units = expand_layout_json_units(json_info)

    assert len(units) == 2
    assert {unit["sheet_no"] for unit in units} == {"PL-01", "EL-01"}
    assert all(unit["is_fragment_unit"] is True for unit in units)
    assert units[0]["json_path"] == ""


def test_expand_layout_json_units_keeps_layout_when_fragments_have_no_identity():
    json_info = {
        "layout_name": "布局1",
        "sheet_no": "",
        "sheet_name": "",
        "json_path": "/tmp/layout.json",
        "data": {
            "layout_name": "布局1",
            "sheet_no": "",
            "sheet_name": "",
            "layout_frames": [{"frame_id": "f1"}, {"frame_id": "f2"}],
            "layout_fragments": [
                {"fragment_id": "frag-1", "frame_id": "f1", "sheet_no": "", "sheet_name": "", "title_blocks": [], "detail_titles": []},
                {"fragment_id": "frag-2", "frame_id": "f2", "sheet_no": "", "sheet_name": "", "title_blocks": [], "detail_titles": []},
            ],
            "is_multi_sheet_layout": True,
        },
    }

    units = expand_layout_json_units(json_info)

    assert len(units) == 1
    assert units[0]["json_path"] == "/tmp/layout.json"
    assert units[0].get("is_fragment_unit") is None


def test_expand_layout_json_units_does_not_split_on_name_only_fragments():
    json_info = {
        "layout_name": "布局1",
        "sheet_no": "",
        "sheet_name": "",
        "json_path": "/tmp/layout.json",
        "data": {
            "layout_name": "布局1",
            "sheet_no": "",
            "sheet_name": "",
            "layout_frames": [{"frame_id": "f1"}, {"frame_id": "f2"}],
            "layout_fragments": [
                {"fragment_id": "frag-1", "frame_id": "f1", "sheet_no": "", "sheet_name": "注：门头钢架设计由专业厂家深化", "title_blocks": [], "detail_titles": []},
                {"fragment_id": "frag-2", "frame_id": "f2", "sheet_no": "", "sheet_name": "图例说明", "title_blocks": [], "detail_titles": []},
            ],
            "is_multi_sheet_layout": True,
        },
    }

    units = expand_layout_json_units(json_info)

    assert len(units) == 1
    assert units[0]["json_path"] == "/tmp/layout.json"


def test_expand_layout_json_units_keeps_dominant_series_even_if_some_fragments_have_no_content():
    json_info = {
        "layout_name": "布局1",
        "sheet_no": "",
        "sheet_name": "",
        "data": {
            "layout_name": "布局1",
            "sheet_no": "",
            "sheet_name": "",
            "layout_frames": [{"frame_id": "f1"}, {"frame_id": "f2"}, {"frame_id": "f3"}],
            "layout_fragments": [
                {
                    "fragment_id": "frag-1",
                    "frame_id": "f1",
                    "sheet_no": "EL-01",
                    "sheet_name": "",
                    "title_blocks": [],
                    "detail_titles": [],
                    "viewports": [{"id": "vp1"}],
                    "dimensions": [],
                    "indexes": [],
                    "materials": [],
                },
                {
                    "fragment_id": "frag-2",
                    "frame_id": "f2",
                    "sheet_no": "EL-02",
                    "sheet_name": "",
                    "title_blocks": [],
                    "detail_titles": [],
                    "viewports": [],
                    "dimensions": [],
                    "indexes": [],
                    "materials": [],
                },
                {
                    "fragment_id": "frag-3",
                    "frame_id": "f3",
                    "sheet_no": "EL-03",
                    "sheet_name": "",
                    "title_blocks": [],
                    "detail_titles": [],
                    "viewports": [],
                    "dimensions": [],
                    "indexes": [],
                    "materials": [],
                },
            ],
            "is_multi_sheet_layout": True,
        },
    }

    units = expand_layout_json_units(json_info)

    assert len(units) == 3
    assert {unit["sheet_no"] for unit in units} == {"EL-01", "EL-02", "EL-03"}


def test_expand_layout_json_units_collapses_directory_like_text_only_layout():
    json_info = {
        "layout_name": "布局1",
        "sheet_no": "",
        "sheet_name": "",
        "json_path": "/tmp/layout.json",
        "data": {
            "layout_name": "布局1",
            "sheet_no": "",
            "sheet_name": "",
            "layout_frames": [{"frame_id": "f1"}, {"frame_id": "f2"}, {"frame_id": "f3"}],
            "layout_fragments": [
                {"fragment_id": "frag-1", "frame_id": "f1", "sheet_no": "IN-01", "sheet_name": "", "title_blocks": [], "detail_titles": [], "viewports": [], "dimensions": [], "indexes": [], "materials": []},
                {"fragment_id": "frag-2", "frame_id": "f2", "sheet_no": "PL-01", "sheet_name": "", "title_blocks": [], "detail_titles": [], "viewports": [], "dimensions": [], "indexes": [], "materials": []},
                {"fragment_id": "frag-3", "frame_id": "f3", "sheet_no": "EL-01", "sheet_name": "", "title_blocks": [], "detail_titles": [], "viewports": [], "dimensions": [], "indexes": [], "materials": []},
            ],
            "is_multi_sheet_layout": True,
        },
    }

    units = expand_layout_json_units(json_info)

    assert len(units) == 1
    assert units[0]["json_path"] == "/tmp/layout.json"
