"""视口/图层 + INSERT 几何分析。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from services.dxf.geo_utils import (
    _bbox_center,
    _bbox_range,
    _collect_virtual_entity_points,
    _point_distance_to_insert,
    _point_xy,
    _safe_float,
)


def calc_model_range(viewport) -> Dict[str, List[float]]:  # noqa: ANN001
    """从 VIEWPORT 计算对应模型空间范围。"""
    if hasattr(viewport, "get_modelspace_limits"):
        try:
            x0, y0, x1, y1 = viewport.get_modelspace_limits()
            if x1 > x0 and y1 > y0:
                return {
                    "min": [round(_safe_float(x0), 3), round(_safe_float(y0), 3)],
                    "max": [round(_safe_float(x1), 3), round(_safe_float(y1), 3)],
                }
        except Exception:  # noqa: BLE001
            pass

    center = getattr(viewport.dxf, "view_center_point", None)
    cx, cy = _point_xy(center)

    model_height = _safe_float(getattr(viewport.dxf, "view_height", 0.0))
    vp_width = _safe_float(getattr(viewport.dxf, "width", 0.0))
    vp_height = _safe_float(getattr(viewport.dxf, "height", 0.0))

    if model_height <= 0.0:
        model_height = _safe_float(vp_height, 0.0)
    if vp_height <= 0.0:
        vp_height = 1.0

    model_width = model_height * (vp_width / vp_height)

    return {
        "min": [round(cx - model_width / 2.0, 3), round(cy - model_height / 2.0, 3)],
        "max": [round(cx + model_width / 2.0, 3), round(cy + model_height / 2.0, 3)],
    }


def get_visible_layers(doc, viewport) -> Set[str]:  # noqa: ANN001
    """获取给定视口下可见图层集合。"""
    layer_names = set()
    for layer in doc.layers:
        name = str(getattr(layer.dxf, "name", "") or "")
        if not name:
            continue
        if layer.is_off() or layer.is_frozen():
            continue
        layer_names.add(name)

    frozen = set()
    if hasattr(viewport, "frozen_layers"):
        try:
            frozen = {str(name) for name in viewport.frozen_layers}
        except Exception:  # noqa: BLE001
            frozen = set()

    if hasattr(viewport, "get_frozen_layer_names"):
        try:
            frozen = frozen.union({str(name) for name in viewport.get_frozen_layer_names()})
        except Exception:  # noqa: BLE001
            pass

    return {name for name in layer_names if name not in frozen}


def _pick_main_viewport(layout) -> Optional[Any]:  # noqa: ANN001
    best_vp = None
    best_area = -1.0

    for vp in layout.query("VIEWPORT"):
        vp_id = int(_safe_float(getattr(vp.dxf, "id", 0), 0.0))
        if vp_id == 1:
            continue

        width = _safe_float(getattr(vp.dxf, "width", 0.0))
        height = _safe_float(getattr(vp.dxf, "height", 0.0))
        area = width * height
        if area > best_area:
            best_area = area
            best_vp = vp

    return best_vp


def _collect_viewports(doc, layout, model_range: Dict[str, List[float]], active_layer: str) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    all_layer_names = {str(getattr(layer.dxf, "name", "") or "") for layer in doc.layers}

    for vp in layout.query("VIEWPORT"):
        vp_id = int(_safe_float(getattr(vp.dxf, "id", 0), 0.0))
        if vp_id == 1:
            continue

        center = _point_xy(getattr(vp.dxf, "center", None))
        scale = _safe_float(getattr(vp.dxf, "scale", 0.0), 0.0)
        vp_model_range = calc_model_range(vp)

        visible = get_visible_layers(doc, vp)
        frozen_in_vp = sorted(all_layer_names - visible) if visible else []

        items.append(
            {
                "id": str(getattr(vp.dxf, "handle", "") or ""),
                "viewport_id": vp_id,
                "position": center,
                "width": _safe_float(getattr(vp.dxf, "width", 0.0), 0.0),
                "height": _safe_float(getattr(vp.dxf, "height", 0.0), 0.0),
                "scale": scale,
                "layer": str(getattr(vp.dxf, "layer", "") or ""),
                "active_layer": active_layer,
                "frozen_layers": frozen_in_vp,
                "model_range": vp_model_range if vp_model_range.get("max") != vp_model_range.get("min") else model_range,
            }
        )
    return items


def _collect_layer_states(doc) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    for layer in doc.layers:
        name = str(getattr(layer.dxf, "name", "") or "")
        is_on = not bool(layer.is_off())
        is_frozen = bool(layer.is_frozen())
        is_locked = bool(layer.is_locked())
        items.append(
            {
                "name": name,
                "visible": bool(is_on and not is_frozen),
                "on": bool(is_on),
                "frozen": bool(is_frozen),
                "locked": bool(is_locked),
            }
        )
    return items


def _collect_insert_head_points(insert) -> List[List[float]]:  # noqa: ANN001
    """Collect visible geometry points around the callout head.

    Many index/detail blocks contain a long leader line. Using the INSERT base point
    or the full block extents pulls the anchor away from the visible callout head.
    We instead use nearby virtual geometry around the insert point.
    """
    insert_point = getattr(insert.dxf, "insert", None)
    if insert_point is None:
        return []

    scale = max(
        abs(_safe_float(getattr(insert.dxf, "xscale", 1.0), 1.0)),
        abs(_safe_float(getattr(insert.dxf, "yscale", 1.0), 1.0)),
        1.0,
    )
    head_radius = 25.0 * scale

    nearby_points: List[List[float]] = []
    try:
        virtual_entities = list(insert.virtual_entities())
    except Exception:  # noqa: BLE001
        virtual_entities = []

    for entity in virtual_entities:
        for point in _collect_virtual_entity_points(entity):
            if _point_distance_to_insert(point, insert_point) <= head_radius:
                nearby_points.append(point)

    for attrib in getattr(insert, "attribs", []):
        point = _point_xy(getattr(attrib.dxf, "insert", None))
        if point != [0.0, 0.0] and _point_distance_to_insert(point, insert_point) <= head_radius * 1.2:
            nearby_points.append(point)

    return nearby_points


def _estimate_insert_visual_anchor(insert) -> List[float]:  # noqa: ANN001
    insert_point = getattr(insert.dxf, "insert", None)
    fallback = _point_xy(insert_point)
    if insert_point is None:
        return fallback

    center = _bbox_center(_collect_insert_head_points(insert))
    return center or fallback


def _estimate_insert_visual_bbox(insert) -> Dict[str, List[float]]:  # noqa: ANN001
    insert_point = getattr(insert.dxf, "insert", None)
    fallback = _point_xy(insert_point)
    scale = max(
        abs(_safe_float(getattr(insert.dxf, "xscale", 1.0), 1.0)),
        abs(_safe_float(getattr(insert.dxf, "yscale", 1.0), 1.0)),
        1.0,
    )
    fallback_half = 12.0 * scale

    bbox = _bbox_range(_collect_insert_head_points(insert))
    if bbox is not None:
        return bbox

    return {
        "min": [round(fallback[0] - fallback_half, 3), round(fallback[1] - fallback_half, 3)],
        "max": [round(fallback[0] + fallback_half, 3), round(fallback[1] + fallback_half, 3)],
    }


def _estimate_index_anchor(insert) -> Tuple[List[float], str]:  # noqa: ANN001
    index_attr_tags = {
        "_ACM-CALLOUTNUMBER",
        "_ACM-SECTIONLABEL",
        "REF#",
        "INDEX_NO",
        "INDEX",
        "NO",
        "NUM",
        "编号",
        "序号",
        "SN",
        "DN",
    }
    target_attr_tags = {
        "_ACM-SHEETNUMBER",
        "SHT",
        "SHEET",
        "TARGET",
        "图号",
        "DRAWINGNO",
        "DRAWNO",
        "SHEETNO",
    }

    index_points: List[List[float]] = []
    target_points: List[List[float]] = []
    for attrib in getattr(insert, "attribs", []):
        tag = str(getattr(attrib.dxf, "tag", "") or "").upper().strip()
        point = _point_xy(getattr(attrib.dxf, "insert", None))
        if point == [0.0, 0.0]:
            continue
        if tag in index_attr_tags:
            index_points.append(point)
        elif tag in target_attr_tags:
            target_points.append(point)

    if index_points and target_points:
        center = _bbox_center(index_points + target_points)
        if center is not None:
            return center, "attribute_center"

    return _estimate_insert_visual_anchor(insert), "nearby_geometry"
