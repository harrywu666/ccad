"""Audit helpers shared across index/dimension/material audits."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


# 功能说明：安全地将值转换为浮点数，失败返回None
def safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# 功能说明：构建审计证据的定位锚点信息
def _safe_bbox_value(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _grid_to_global_pct(grid: str) -> Optional[Dict[str, float]]:
    match = re.fullmatch(r"\s*([A-Xa-x])\s*(\d{1,2})\s*", str(grid or ""))
    if not match:
        return None
    col = ord(match.group(1).upper()) - ord("A")
    row = int(match.group(2)) - 1
    if not (0 <= col < 24 and 0 <= row < 17):
        return None
    cell_width = 100.0 / 24.0
    cell_height = 100.0 / 17.0
    return {
        "x": round((col + 0.5) * cell_width, 1),
        "y": round((row + 0.5) * cell_height, 1),
    }


def _normalize_highlight_region(highlight_region: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(highlight_region, dict):
        return None
    bbox = highlight_region.get("bbox_pct")
    if not isinstance(bbox, dict):
        return None
    x = _safe_bbox_value(bbox.get("x"))
    y = _safe_bbox_value(bbox.get("y"))
    width = _safe_bbox_value(bbox.get("width"))
    height = _safe_bbox_value(bbox.get("height"))
    if None in {x, y, width, height}:
        return None
    width = max(0.5, min(100.0, width or 0.0))
    height = max(0.5, min(100.0, height or 0.0))
    x = max(0.0, min(100.0 - width, x or 0.0))
    y = max(0.0, min(100.0 - height, y or 0.0))
    shape = str(highlight_region.get("shape") or "cloud_rect").strip() or "cloud_rect"
    origin = str(highlight_region.get("origin") or "inferred").strip() or "inferred"
    return {
        "shape": shape,
        "bbox_pct": {
            "x": round(x, 1),
            "y": round(y, 1),
            "width": round(width, 1),
            "height": round(height, 1),
        },
        "origin": origin,
    }


def _default_highlight_region_from_point(global_pct: Dict[str, float], *, origin: str) -> Dict[str, Any]:
    side = 4.2
    center_x = float(global_pct["x"])
    center_y = float(global_pct["y"])
    return {
        "shape": "cloud_rect",
        "bbox_pct": {
            "x": round(max(0.0, min(100.0 - side, center_x - side / 2.0)), 1),
            "y": round(max(0.0, min(100.0 - side, center_y - side / 2.0)), 1),
            "width": round(side, 1),
            "height": round(side, 1),
        },
        "origin": origin,
    }


def build_anchor(
    *,
    role: str,
    sheet_no: Optional[str],
    grid: Optional[str] = None,
    global_pct: Optional[Dict[str, Any]] = None,
    confidence: Optional[float] = None,
    origin: str = "inferred",
    highlight_region: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    anchor: Dict[str, Any] = {
        "role": role,
        "sheet_no": (sheet_no or "").strip(),
        "grid": (grid or "").strip(),
        "origin": origin,
    }

    if global_pct and isinstance(global_pct, dict):
        x = safe_float(global_pct.get("x"))
        y = safe_float(global_pct.get("y"))
        if x is not None and y is not None:
            anchor["global_pct"] = {
                "x": round(max(0.0, min(100.0, x)), 1),
                "y": round(max(0.0, min(100.0, y)), 1),
            }
    elif anchor["grid"]:
        inferred_pct = _grid_to_global_pct(anchor["grid"])
        if inferred_pct is not None:
            anchor["global_pct"] = inferred_pct

    if confidence is not None:
        conf = safe_float(confidence)
        if conf is not None:
            anchor["confidence"] = round(max(0.0, min(1.0, conf)), 3)

    normalized_region = _normalize_highlight_region(highlight_region)
    if normalized_region is None and isinstance(anchor.get("global_pct"), dict):
        normalized_region = _default_highlight_region_from_point(anchor["global_pct"], origin=origin)
    if normalized_region is not None:
        anchor["highlight_region"] = normalized_region
        if "global_pct" not in anchor:
            bbox = normalized_region["bbox_pct"]
            anchor["global_pct"] = {
                "x": round(float(bbox["x"]) + float(bbox["width"]) / 2.0, 1),
                "y": round(float(bbox["y"]) + float(bbox["height"]) / 2.0, 1),
            }

    if isinstance(meta, dict):
        for key, value in meta.items():
            if value is None:
                continue
            anchor[key] = value

    if not anchor["sheet_no"]:
        return None
    if "global_pct" not in anchor and not anchor["grid"]:
        return None
    return anchor


# 功能说明：将锚点列表转换为证据JSON字符串
def to_evidence_json(
    anchors: List[Dict[str, Any]],
    *,
    pair_id: Optional[str] = None,
    unlocated_reason: Optional[str] = None,
) -> str:
    payload: Dict[str, Any] = {"anchors": anchors or []}
    if pair_id:
        payload["pair_id"] = pair_id
    if unlocated_reason:
        payload["unlocated_reason"] = unlocated_reason
    return json.dumps(payload, ensure_ascii=False)
