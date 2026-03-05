"""
坐标计算服务
负责将CAD模型坐标映射为图像百分比坐标，并补充棋盘格/象限信息。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

GRID_COLS = 24
GRID_ROWS = 17
GRID_OVERLAP = 0.20
COL_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWX"


def cad_to_global_pct(cad_x: float, cad_y: float, model_range: Dict[str, List[float]]) -> Tuple[float, float]:
    """
    CAD模型空间坐标 -> 全图百分比坐标（0~100）
    注意：Y轴翻转（CAD向上为正，图像向下为正）
    """
    x_min, y_min = model_range.get("min", [0.0, 0.0])
    x_max, y_max = model_range.get("max", [0.0, 0.0])

    if x_max == x_min or y_max == y_min:
        return 50.0, 50.0

    pct_x = (float(cad_x) - float(x_min)) / (float(x_max) - float(x_min)) * 100.0
    pct_y = (1.0 - (float(cad_y) - float(y_min)) / (float(y_max) - float(y_min))) * 100.0

    pct_x = max(0.0, min(100.0, round(pct_x, 1)))
    pct_y = max(0.0, min(100.0, round(pct_y, 1)))
    return pct_x, pct_y


def global_pct_to_grid(pct_x: float, pct_y: float) -> str:
    """
    全图百分比坐标 -> 棋盘格坐标（A1-X17）
    """
    col_idx = int(float(pct_x) / 100.0 * GRID_COLS)
    row_idx = int(float(pct_y) / 100.0 * GRID_ROWS)
    col_idx = max(0, min(GRID_COLS - 1, col_idx))
    row_idx = max(0, min(GRID_ROWS - 1, row_idx))
    return f"{COL_LABELS[col_idx]}{row_idx + 1}"


def global_pct_to_quadrants(pct_x: float, pct_y: float, overlap: float = GRID_OVERLAP) -> Dict[str, Dict[str, float]]:
    """
    全图百分比坐标 -> 象限内局部百分比坐标。
    落在重叠带的点会命中多个象限。
    """
    ext = (float(overlap) / 2.0) * 100.0
    half = 50.0

    quadrant_ranges = {
        "图2左上": {"x": (0.0, half + ext), "y": (0.0, half + ext)},
        "图3右上": {"x": (half - ext, 100.0), "y": (0.0, half + ext)},
        "图4左下": {"x": (0.0, half + ext), "y": (half - ext, 100.0)},
        "图5右下": {"x": (half - ext, 100.0), "y": (half - ext, 100.0)},
    }

    result: Dict[str, Dict[str, float]] = {}
    for name, ranges in quadrant_ranges.items():
        x0, x1 = ranges["x"]
        y0, y1 = ranges["y"]
        if x0 <= pct_x <= x1 and y0 <= pct_y <= y1:
            local_x = (pct_x - x0) / (x1 - x0) * 100.0
            local_y = (pct_y - y0) / (y1 - y0) * 100.0
            result[name] = {
                "local_x_pct": round(local_x, 1),
                "local_y_pct": round(local_y, 1),
            }

    return result


def _enrich_point_item(item: Dict, pos_key: str, model_range: Dict[str, List[float]]) -> Dict:
    pos = item.get(pos_key)
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        return item

    try:
        cad_x = float(pos[0])
        cad_y = float(pos[1])
    except (TypeError, ValueError):
        return item

    pct_x, pct_y = cad_to_global_pct(cad_x, cad_y, model_range)
    item["global_pct"] = {"x": pct_x, "y": pct_y}
    item["grid"] = global_pct_to_grid(pct_x, pct_y)
    item["in_quadrants"] = global_pct_to_quadrants(pct_x, pct_y)
    return item


def enrich_json_with_coordinates(layout_json: Dict) -> Dict:
    """
    为 dimensions/indexes/materials 增强坐标信息：
    - global_pct
    - grid
    - in_quadrants
    """
    model_range = layout_json.get("model_range")
    if not isinstance(model_range, dict):
        return layout_json

    enriched = dict(layout_json)
    enriched["dimensions"] = [
        _enrich_point_item(dict(item), "text_position", model_range)
        for item in layout_json.get("dimensions", [])
    ]
    enriched["indexes"] = [
        _enrich_point_item(dict(item), "position", model_range)
        for item in layout_json.get("indexes", [])
    ]
    enriched["materials"] = [
        _enrich_point_item(dict(item), "position", model_range)
        for item in layout_json.get("materials", [])
    ]
    return enriched
