from __future__ import annotations

import sys
from pathlib import Path

import ezdxf


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.dxf_service import (
    _estimate_index_anchor,
    _estimate_insert_visual_anchor,
    _estimate_insert_visual_bbox,
    _extract_insert_info,
    extract_layout,
)
from services.dxf_service import _extract_layout_page_range


def _build_index_block(doc: ezdxf.EzDxf) -> str:
    block = doc.blocks.new(name="IDX")
    block.add_lwpolyline(
        [
            (0.0, 5.0),
            (0.0, 7.071),
            (-7.071, 0.0),
            (0.0, -7.071),
            (0.0, -5.0),
        ]
    )
    block.add_lwpolyline([(0.0, -15.0), (0.0, -220.0)])
    block.add_lwpolyline([(-5.0, 0.0), (5.0, 0.0)])
    block.add_lwpolyline([(0.0, 5.0), (0.0, -5.0)])
    return block.name


def test_estimate_insert_visual_anchor_uses_symbol_head_geometry():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    block_name = _build_index_block(doc)
    insert = layout.add_blockref(block_name, (541.48, 287.771))

    anchor = _estimate_insert_visual_anchor(insert)

    assert anchor == [540.445, 283.807]


def test_estimate_index_anchor_prefers_attribute_center():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    block_name = _build_index_block(doc)
    insert = layout.add_blockref(block_name, (541.48, 287.771))
    insert.add_attrib("_ACM-SECTIONLABEL", "3", insert=(540.509, 289.047))
    insert.add_attrib("_ACM-SHEETNUMBER", "A06.02b", insert=(537.855, 284.365))

    anchor, anchor_source = _estimate_index_anchor(insert)

    assert anchor == [539.182, 286.706]
    assert anchor_source == "attribute_center"


def test_estimate_insert_visual_anchor_falls_back_to_insert_without_nearby_geometry():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    block = doc.blocks.new(name="EMPTY")
    block.add_lwpolyline([(0.0, -120.0), (0.0, -220.0)])
    insert = layout.add_blockref(block.name, (200.0, 100.0))

    anchor = _estimate_insert_visual_anchor(insert)

    assert anchor == [200.0, 100.0]


def test_estimate_insert_visual_bbox_covers_callout_head():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    block_name = _build_index_block(doc)
    insert = layout.add_blockref(block_name, (541.48, 287.771))
    insert.add_attrib("_ACM-SECTIONLABEL", "3", insert=(540.509, 289.047))
    insert.add_attrib("_ACM-SHEETNUMBER", "A06.02b", insert=(537.855, 284.365))

    bbox = _estimate_insert_visual_bbox(insert)

    assert bbox["min"][0] < 538.0
    assert bbox["min"][1] < 281.0
    assert bbox["max"][0] > 541.0
    assert bbox["max"][1] > 289.0


def test_extract_layout_page_range_prefers_paper_size_over_limits():
    class _Dxf:
        limmin = (-17.995, -17.985, 0.0)
        limmax = (823.005, 1170.815, 0.0)
        plot_origin_x_offset = 0.0
        plot_origin_y_offset = 0.0
        paper_width = 841.0
        paper_height = 594.0

    class _Layout:
        dxf = _Dxf()

    assert _extract_layout_page_range(_Layout()) == {
        "min": [0.0, 0.0],
        "max": [841.0, 594.0],
    }


def test_extract_insert_info_collects_modelspace_detail_titles_visible_in_viewport():
    doc = ezdxf.new("R2018")
    model = doc.modelspace()
    layout = doc.layouts.get("Layout1")

    block = doc.blocks.new(name="DET_TITLE")
    block.add_attdef("DN", insert=(0.0, 0.0))
    block.add_attdef("TITLE1", insert=(15.0, 0.0))
    block.add_attdef("TITLE3", insert=(15.0, -8.0))

    insert = model.add_blockref(block.name, (120.0, 60.0), dxfattribs={"layer": "G-ANNO-TITL"})
    insert.add_auto_attribs({"DN": "A1", "TITLE1": "D01 前厅门", "TITLE3": "DETAIL - LOBBY DOOR"})

    indexes, title_blocks, detail_titles, _, _ = _extract_insert_info(
        doc,
        layout,
        {"min": [0.0, 0.0], "max": [200.0, 100.0]},
        {"G-ANNO-TITL"},
    )

    assert indexes == []
    assert title_blocks == []
    assert len(detail_titles) == 1
    assert detail_titles[0]["label"] == "A1"
    assert detail_titles[0]["title_lines"] == ["D01 前厅门", "DETAIL - LOBBY DOOR"]
    assert detail_titles[0]["source"] == "model_space"


def _build_title_block(doc: ezdxf.EzDxf, name: str = "TITLE_BLOCK") -> str:
    block = doc.blocks.new(name=name)
    block.add_attdef("DRAWNO", insert=(0.0, 0.0))
    block.add_attdef("DRAWNAME", insert=(20.0, 0.0))
    return block.name


def _add_rect(layout, x0: float, y0: float, x1: float, y1: float) -> None:
    layout.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
        close=True,
    )


def test_extract_layout_detects_single_frame_and_fragment():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    layout.dxf.paper_width = 841.0
    layout.dxf.paper_height = 594.0
    _add_rect(layout, 10.0, 10.0, 810.0, 560.0)

    title_block = _build_title_block(doc)
    insert = layout.add_blockref(title_block, (700.0, 40.0), dxfattribs={"layer": "G-ANNO-TITL"})
    insert.add_auto_attribs({"DRAWNO": "A1.01", "DRAWNAME": "平面布置图"})

    payload = extract_layout(doc, "Layout1", "single-frame.dwg")

    assert payload is not None
    assert payload["is_multi_sheet_layout"] is False
    assert len(payload["layout_frames"]) == 1
    assert len(payload["layout_fragments"]) == 1
    assert payload["layout_fragments"][0]["sheet_no"] == "A1.01"
    assert payload["layout_fragments"][0]["sheet_name"] == "平面布置图"
    assert payload["layout_frames"][0]["orientation"] == "landscape"


def test_extract_layout_detects_multiple_frames_as_multi_sheet_layout():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    layout.dxf.paper_width = 841.0
    layout.dxf.paper_height = 594.0

    _add_rect(layout, 20.0, 40.0, 390.0, 540.0)
    _add_rect(layout, 430.0, 40.0, 800.0, 540.0)

    title_block = _build_title_block(doc)
    left = layout.add_blockref(title_block, (250.0, 70.0), dxfattribs={"layer": "G-ANNO-TITL"})
    left.add_auto_attribs({"DRAWNO": "PL-01", "DRAWNAME": "平面图"})
    right = layout.add_blockref(title_block, (660.0, 70.0), dxfattribs={"layer": "G-ANNO-TITL"})
    right.add_auto_attribs({"DRAWNO": "EL-01", "DRAWNAME": "立面图"})

    payload = extract_layout(doc, "Layout1", "multi-frame.dwg")

    assert payload is not None
    assert payload["is_multi_sheet_layout"] is True
    assert len(payload["layout_frames"]) == 2
    assert len(payload["layout_fragments"]) == 2
    sheet_nos = {item["sheet_no"] for item in payload["layout_fragments"]}
    assert sheet_nos == {"PL-01", "EL-01"}


def test_extract_layout_prefers_outer_frame_over_inner_geometry():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    layout.dxf.paper_width = 841.0
    layout.dxf.paper_height = 594.0

    _add_rect(layout, 10.0, 10.0, 810.0, 560.0)
    _add_rect(layout, 100.0, 100.0, 220.0, 220.0)

    title_block = _build_title_block(doc)
    insert = layout.add_blockref(title_block, (700.0, 40.0), dxfattribs={"layer": "G-ANNO-TITL"})
    insert.add_auto_attribs({"DRAWNO": "A1.02", "DRAWNAME": "天花图"})

    payload = extract_layout(doc, "Layout1", "outer-frame.dwg")

    assert payload is not None
    assert len(payload["layout_frames"]) == 1
    bbox = payload["layout_frames"][0]["frame_bbox"]
    assert bbox["min"] == [10.0, 10.0]
    assert bbox["max"] == [810.0, 560.0]


def test_extract_layout_fragment_infers_identity_from_texts():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    layout.dxf.paper_width = 841.0
    layout.dxf.paper_height = 594.0

    _add_rect(layout, 20.0, 80.0, 390.0, 520.0)
    _add_rect(layout, 430.0, 80.0, 800.0, 520.0)

    layout.add_text("PL-01", dxfattribs={"insert": (60.0, 54.0)})
    layout.add_text("平面布置图", dxfattribs={"insert": (120.0, 54.0)})
    layout.add_text("EL-01", dxfattribs={"insert": (470.0, 54.0)})
    layout.add_text("立面图", dxfattribs={"insert": (530.0, 54.0)})

    payload = extract_layout(doc, "Layout1", "text-fragment.dwg")

    assert payload is not None
    assert payload["is_multi_sheet_layout"] is True
    assert len(payload["layout_fragments"]) == 2
    fragment_map = {item["sheet_no"]: item for item in payload["layout_fragments"]}
    assert set(fragment_map) == {"PL-01", "EL-01"}
    assert fragment_map["PL-01"]["sheet_name"] == "平面布置图"
    assert fragment_map["EL-01"]["sheet_name"] == "立面图"


def test_extract_layout_fragment_infers_identity_from_bottom_center_texts():
    doc = ezdxf.new("R2018")
    layout = doc.layouts.get("Layout1")
    layout.dxf.paper_width = 841.0
    layout.dxf.paper_height = 594.0

    _add_rect(layout, 120.0, 120.0, 720.0, 500.0)

    layout.add_text("图号", dxfattribs={"insert": (360.0, 92.0)})
    layout.add_text("DT-08", dxfattribs={"insert": (380.0, 92.0)})
    layout.add_text("图名", dxfattribs={"insert": (360.0, 72.0)})
    layout.add_text("节点详图", dxfattribs={"insert": (430.0, 72.0)})

    payload = extract_layout(doc, "Layout1", "center-title-zone.dwg")

    assert payload is not None
    assert len(payload["layout_fragments"]) == 1
    fragment = payload["layout_fragments"][0]
    assert fragment["sheet_no"] == "DT-08"
    assert fragment["sheet_name"] == "节点详图"
