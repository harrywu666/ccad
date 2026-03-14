from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.coordinate_service import enrich_json_with_coordinates
from services.review_kernel.ir_compiler import compile_layout_ir


def _is_bbox_outside_layout(bbox: object, layout_bbox: object) -> bool:
    if not isinstance(bbox, list) or len(bbox) < 4:
        return False
    if not isinstance(layout_bbox, list) or len(layout_bbox) < 4:
        return False
    try:
        x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        lx0, ly0, lx1, ly1 = (
            float(layout_bbox[0]),
            float(layout_bbox[1]),
            float(layout_bbox[2]),
            float(layout_bbox[3]),
        )
    except (TypeError, ValueError):
        return False
    return (x1 < lx0) or (x0 > lx1) or (y1 < ly0) or (y0 > ly1)


def test_review_kernel_coordinate_quality_gate():
    workspace_root = Path(__file__).resolve().parents[2]
    layout_json_files = sorted((workspace_root / "projects").glob("**/*_layout_v1.json"))
    if not layout_json_files:
        pytest.skip("未找到布局 JSON 样本，跳过坐标质量门禁。")

    totals = {"dimension": 0, "text": 0, "insert": 0}
    outside = {"dimension": 0, "text": 0, "insert": 0}

    for json_path in layout_json_files:
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue

        payload = enrich_json_with_coordinates(payload)
        ir = compile_layout_ir(payload, source_json_path=str(json_path))
        review_view = (ir.get("semantic_layer", {}).get("review_views") or [{}])[0]
        layout_bbox = review_view.get("bbox_in_paper")
        entities = ir.get("normalized_layer", {}).get("normalized_entities") or []

        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_type = str(entity.get("entity_type") or "")
            if entity_type not in totals:
                continue
            totals[entity_type] += 1
            if _is_bbox_outside_layout(entity.get("bbox"), layout_bbox):
                outside[entity_type] += 1

    thresholds = {
        "dimension": 0.05,
        "text": 0.05,
        "insert": 0.05,
    }
    for entity_type, threshold in thresholds.items():
        total = totals[entity_type]
        if total == 0:
            continue
        ratio = outside[entity_type] / total
        assert ratio <= threshold, (
            f"{entity_type} 坐标越界率过高: {outside[entity_type]}/{total}={ratio:.2%}, "
            f"阈值={threshold:.2%}"
        )
