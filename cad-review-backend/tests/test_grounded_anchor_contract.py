from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.audit.common import build_anchor, to_evidence_json
from services.coordinate_service import enrich_json_with_coordinates


def test_build_anchor_auto_adds_cloud_region_from_point():
    anchor = build_anchor(
        role="source",
        sheet_no="A1.01",
        global_pct={"x": 48.2, "y": 37.4},
        confidence=0.9,
        origin="index",
    )

    assert anchor is not None
    assert anchor["highlight_region"]["shape"] == "cloud_rect"
    assert anchor["highlight_region"]["bbox_pct"]["width"] > 0
    assert anchor["highlight_region"]["bbox_pct"]["height"] > 0


def test_to_evidence_json_keeps_multiple_anchor_regions():
    anchors = [
        build_anchor(
            role="source",
            sheet_no="A1.01",
            global_pct={"x": 22.5, "y": 31.4},
            confidence=0.9,
            origin="index",
        ),
        build_anchor(
            role="source",
            sheet_no="A1.01",
            global_pct={"x": 52.5, "y": 61.4},
            confidence=0.9,
            origin="index",
        ),
    ]

    payload = json.loads(to_evidence_json([anchor for anchor in anchors if anchor]))

    assert isinstance(payload["anchors"], list)
    assert len(payload["anchors"]) == 2
    assert all(anchor.get("highlight_region") for anchor in payload["anchors"])


def test_enrich_json_with_coordinates_enriches_material_table_locations():
    payload = {
        "sheet_no": "M1.01",
        "model_range": {"min": [0.0, 0.0], "max": [100.0, 100.0]},
        "material_table": [
            {
                "code": "M01",
                "name": "石材",
                "position": [50.0, 50.0],
                "source": "layout_space",
                "symbol_bbox": {"min": [44.0, 46.0], "max": [56.0, 54.0]},
            }
        ],
    }

    enriched = enrich_json_with_coordinates(payload)
    item = enriched["material_table"][0]

    assert item["global_pct"] == {"x": 50.0, "y": 50.0}
    assert item["highlight_region"]["shape"] == "cloud_rect"
