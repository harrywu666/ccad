from __future__ import annotations

import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.coordinate_service import enrich_json_with_coordinates


def test_enrich_json_uses_layout_space_range_for_layout_indexes():
    layout_json = {
        "model_range": {
            "min": [69267.893, 925.361],
            "max": [75569.527, 5218.926],
        },
        "dimensions": [
            {
                "text_position": [74987.349, 1187.757],
                "source": "model_space",
            },
            {
                "text_position": [74252.293, 1187.757],
                "source": "model_space",
            },
        ],
        "indexes": [
            {
                "index_no": "3",
                "target_sheet": "A06.00a",
                "position": [264.329, 450.872],
                "source": "layout_space",
            },
            {
                "index_no": "4",
                "target_sheet": "A6.00a",
                "position": [444.394, 527.813],
                "source": "layout_space",
            },
        ],
        "title_blocks": [
            {
                "position": [125.137, 472.989],
                "sheet_name": "MW.01 -1",
            },
            {
                "position": [125.137, 21.402],
                "sheet_name": "MW.01 -2",
            },
        ],
        "viewports": [
            {
                "viewport_id": 2,
                "position": [384.681, 529.846],
                "width": 630.1633284024895,
                "height": 94.80825733475251,
            },
            {
                "viewport_id": 3,
                "position": [384.681, 245.65],
                "width": 630.1633284024895,
                "height": 429.3564613320139,
            },
        ],
    }

    enriched = enrich_json_with_coordinates(layout_json)
    index3 = enriched["indexes"][0]

    assert index3["global_pct"] == {"x": 30.9, "y": 22.7}
    assert index3["grid"] == "H4"


def test_enrich_json_prefers_explicit_layout_page_range_over_viewport_bbox():
    layout_json = {
        "layout_page_range": {
            "min": [0.0, 0.0],
            "max": [841.0, 594.0],
        },
        "model_range": {
            "min": [165630.161, 10778.667],
            "max": [175487.829, 13896.779],
        },
        "indexes": [
            {
                "index_no": "2",
                "target_sheet": "A06.02a",
                "position": [376.937, 325.578],
                "source": "layout_space",
            }
        ],
        "title_blocks": [
            {"position": [67.572, 21.402], "sheet_name": "MW.01 -2"},
            {"position": [67.572, 346.583], "sheet_name": "MW.01 -1"},
        ],
        "viewports": [
            {"viewport_id": 2, "position": [372.475, 466.079], "width": 657.177848590359, "height": 207.874165004616},
            {"viewport_id": 3, "position": [372.475, 180.359], "width": 657.1778485903596, "height": 305.7202772156462},
        ],
    }

    enriched = enrich_json_with_coordinates(layout_json)
    index2 = enriched["indexes"][0]

    assert index2["global_pct"] == {"x": 44.8, "y": 45.2}
    assert index2["grid"] == "K8"


def test_enrich_json_uses_fragment_bbox_for_layout_space_items():
    layout_json = {
        "layout_page_range": {
            "min": [0.0, 0.0],
            "max": [1000.0, 1000.0],
        },
        "fragment_bbox": {
            "min": [100.0, 100.0],
            "max": [300.0, 300.0],
        },
        "indexes": [
            {
                "index_no": "A1",
                "position": [150.0, 250.0],
                "source": "layout_space",
            }
        ],
    }

    enriched = enrich_json_with_coordinates(layout_json)
    index_item = enriched["indexes"][0]

    assert index_item["global_pct"] == {"x": 25.0, "y": 25.0}
    assert index_item["grid"] == "G5"


def test_enrich_json_projects_model_space_items_through_fragment_viewport():
    layout_json = {
        "layout_page_range": {
            "min": [0.0, 0.0],
            "max": [1000.0, 1000.0],
        },
        "fragment_bbox": {
            "min": [100.0, 100.0],
            "max": [300.0, 300.0],
        },
        "viewports": [
            {
                "viewport_id": 2,
                "position": [200.0, 200.0],
                "width": 200.0,
                "height": 200.0,
                "model_range": {
                    "min": [0.0, 0.0],
                    "max": [100.0, 100.0],
                },
            }
        ],
        "dimensions": [
            {
                "text_position": [25.0, 75.0],
                "source": "model_space",
            }
        ],
    }

    enriched = enrich_json_with_coordinates(layout_json)
    dim_item = enriched["dimensions"][0]

    assert dim_item["global_pct"] == {"x": 25.0, "y": 25.0}
    assert dim_item["grid"] == "G5"


def test_enrich_json_projects_model_space_pseudo_texts_and_inserts():
    layout_json = {
        "layout_page_range": {
            "min": [0.0, 0.0],
            "max": [1000.0, 1000.0],
        },
        "fragment_bbox": {
            "min": [100.0, 100.0],
            "max": [300.0, 300.0],
        },
        "viewports": [
            {
                "viewport_id": 2,
                "position": [200.0, 200.0],
                "width": 200.0,
                "height": 200.0,
                "model_range": {
                    "min": [0.0, 0.0],
                    "max": [100.0, 100.0],
                },
            }
        ],
        "pseudo_texts": [
            {
                "position": [25.0, 75.0],
                "source": "model_space",
            }
        ],
        "insert_entities": [
            {
                "position": [25.0, 75.0],
                "source": "model_space",
            }
        ],
    }

    enriched = enrich_json_with_coordinates(layout_json)
    text_item = enriched["pseudo_texts"][0]
    insert_item = enriched["insert_entities"][0]

    assert text_item["global_pct"] == {"x": 25.0, "y": 25.0}
    assert text_item["grid"] == "G5"
    assert insert_item["global_pct"] == {"x": 25.0, "y": 25.0}
    assert insert_item["grid"] == "G5"


def _scaled_layout_case(
    scale_x: float,
    scale_y: float,
    include_title_block: bool = False,
) -> dict:
    viewport_width = 1000.0 * scale_x
    viewport_height = 400.0 * scale_y
    viewport_center = [500.0 * scale_x, 200.0 * scale_y]
    index_position = [250.0 * scale_x, 300.0 * scale_y]

    layout_json = {
        "model_range": {
            "min": [70000.0, 1000.0],
            "max": [76000.0, 5000.0],
        },
        "dimensions": [
            {
                "text_position": [73000.0, 1800.0],
                "source": "model_space",
            }
        ],
        "indexes": [
            {
                "index_no": "3",
                "target_sheet": "A06.00a",
                "position": index_position,
                "source": "layout_space",
            }
        ],
        "viewports": [
            {
                "viewport_id": 2,
                "position": viewport_center,
                "width": viewport_width,
                "height": viewport_height,
            }
        ],
        "title_blocks": [],
    }

    if include_title_block:
        layout_json["title_blocks"] = [
            {
                "position": [-50.0 * scale_x, -20.0 * scale_y],
                "sheet_name": "Scaled Title Block",
            }
        ]
        layout_json["indexes"][0]["position"] = [475.0 * scale_x, 190.0 * scale_y]

    return layout_json


@pytest.mark.parametrize(
    ("label", "scale_x", "scale_y"),
    [
        ("a3_like", 0.7, 0.7),
        ("a0_like", 1.6, 1.6),
        ("ultra_wide", 2.8, 0.6),
        ("ultra_tall", 0.6, 2.4),
    ],
)
def test_enrich_json_layout_space_mapping_is_aspect_ratio_agnostic(label: str, scale_x: float, scale_y: float):
    del label
    enriched = enrich_json_with_coordinates(_scaled_layout_case(scale_x=scale_x, scale_y=scale_y))
    index_item = enriched["indexes"][0]

    assert index_item["global_pct"] == {"x": 25.0, "y": 25.0}
    assert index_item["grid"] == "G5"


@pytest.mark.parametrize(
    ("label", "scale_x", "scale_y"),
    [
        ("a2_like", 1.2, 1.2),
        ("panoramic", 3.0, 0.8),
        ("compact_tall", 0.8, 2.0),
    ],
)
def test_enrich_json_layout_space_mapping_with_title_block_scales_across_layout_sizes(
    label: str,
    scale_x: float,
    scale_y: float,
):
    del label
    enriched = enrich_json_with_coordinates(
        _scaled_layout_case(scale_x=scale_x, scale_y=scale_y, include_title_block=True)
    )
    index_item = enriched["indexes"][0]

    assert index_item["global_pct"] == {"x": 50.0, "y": 50.0}
    assert index_item["grid"] == "M9"
