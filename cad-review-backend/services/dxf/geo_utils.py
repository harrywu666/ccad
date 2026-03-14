"""几何/数学工具函数。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _point_xy(point: Any) -> List[float]:
    if point is None:
        return [0.0, 0.0]

    if hasattr(point, "x") and hasattr(point, "y"):
        return [round(_safe_float(point.x), 3), round(_safe_float(point.y), 3)]

    if isinstance(point, Sequence) and len(point) >= 2:
        return [round(_safe_float(point[0]), 3), round(_safe_float(point[1]), 3)]

    return [0.0, 0.0]


def _point_xyz(point: Any) -> List[float]:
    if point is None:
        return [0.0, 0.0, 0.0]

    if hasattr(point, "x") and hasattr(point, "y"):
        z = getattr(point, "z", 0.0)
        return [
            round(_safe_float(point.x), 3),
            round(_safe_float(point.y), 3),
            round(_safe_float(z), 3),
        ]

    if isinstance(point, Sequence) and len(point) >= 2:
        z = point[2] if len(point) >= 3 else 0.0
        return [
            round(_safe_float(point[0]), 3),
            round(_safe_float(point[1]), 3),
            round(_safe_float(z), 3),
        ]

    return [0.0, 0.0, 0.0]


def _classify_elevation_band(
    z_min: float,
    z_max: float,
    *,
    layer_name: str = "",
) -> tuple[str, bool]:
    normalized_layer = str(layer_name or "").upper()
    if z_max <= 50 and z_min >= -100:
        if any(token in normalized_layer for token in ("WALL", "DOOR", "MEN", "门", "窗", "WINDOW")):
            return "human_accessible", False
        if not normalized_layer:
            return "human_accessible", True
        return "floor_level", False
    if z_max <= 2400:
        return "human_accessible", False
    if z_max <= 3000:
        return "overhead", False
    return "structural", False


def _point_in_range(point: Sequence[float], model_range: Dict[str, List[float]], padding: float = 0.0) -> bool:
    if len(point) < 2:
        return False
    min_x, min_y = model_range.get("min", [0.0, 0.0])
    max_x, max_y = model_range.get("max", [0.0, 0.0])
    x, y = _safe_float(point[0]), _safe_float(point[1])
    return (min_x - padding) <= x <= (max_x + padding) and (min_y - padding) <= y <= (max_y + padding)


def _point_in_any_range(
    point: Sequence[float],
    model_ranges: Optional[Sequence[Dict[str, List[float]]]],
    *,
    fallback_range: Optional[Dict[str, List[float]]] = None,
    padding: float = 0.0,
) -> bool:
    ranges = [item for item in (model_ranges or []) if item]
    if not ranges and fallback_range:
        ranges = [fallback_range]
    for model_range in ranges:
        if _point_in_range(point, model_range, padding=padding):
            return True
    return False


def _distance(p1: Sequence[float], p2: Sequence[float]) -> float:
    if len(p1) < 2 or len(p2) < 2:
        return 1e9
    dx = _safe_float(p1[0]) - _safe_float(p2[0])
    dy = _safe_float(p1[1]) - _safe_float(p2[1])
    return (dx * dx + dy * dy) ** 0.5


def _point_distance_to_insert(point: Sequence[float], insert_point: Any) -> float:
    if len(point) < 2 or insert_point is None:
        return 1e9
    try:
        insert_x = _safe_float(getattr(insert_point, "x", insert_point[0]))
        insert_y = _safe_float(getattr(insert_point, "y", insert_point[1]))
    except (TypeError, IndexError):
        return 1e9
    return _distance(point, [insert_x, insert_y])


def _collect_virtual_entity_points(entity) -> List[List[float]]:  # noqa: ANN001
    points: List[List[float]] = []
    entity_type = entity.dxftype()

    try:
        if entity_type == "LWPOLYLINE":
            points.extend([[float(p[0]), float(p[1])] for p in entity.get_points("xy")])
        elif entity_type == "POLYLINE":
            points.extend([[float(vertex.dxf.location.x), float(vertex.dxf.location.y)] for vertex in entity.vertices])
        elif entity_type == "LINE":
            points.append([float(entity.dxf.start.x), float(entity.dxf.start.y)])
            points.append([float(entity.dxf.end.x), float(entity.dxf.end.y)])
        elif entity_type in {"CIRCLE", "ARC"}:
            center = entity.dxf.center
            radius = float(entity.dxf.radius)
            points.extend(
                [
                    [float(center.x - radius), float(center.y - radius)],
                    [float(center.x + radius), float(center.y + radius)],
                ]
            )
        elif entity_type == "SOLID":
            for vertex_name in ("vtx0", "vtx1", "vtx2", "vtx3"):
                vertex = getattr(entity.dxf, vertex_name, None)
                if vertex is not None:
                    points.append([float(vertex.x), float(vertex.y)])
        elif entity_type in {"TEXT", "MTEXT", "ATTDEF"}:
            insert = getattr(entity.dxf, "insert", None)
            if insert is not None:
                points.append([float(insert.x), float(insert.y)])
    except Exception:  # noqa: BLE001
        return []

    return points


def _bbox_center(points: Sequence[Sequence[float]]) -> Optional[List[float]]:
    if len(points) < 2:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [round((min(xs) + max(xs)) / 2.0, 3), round((min(ys) + max(ys)) / 2.0, 3)]


def _bbox_range(points: Sequence[Sequence[float]]) -> Optional[Dict[str, List[float]]]:
    if len(points) < 2:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return {
        "min": [round(min(xs), 3), round(min(ys), 3)],
        "max": [round(max(xs), 3), round(max(ys), 3)],
    }


def _bbox_contains_point(bbox: Dict[str, List[float]], point: Sequence[float], padding: float = 0.0) -> bool:
    if len(point) < 2:
        return False
    bbox_min = bbox.get("min") or [0.0, 0.0]
    bbox_max = bbox.get("max") or [0.0, 0.0]
    if len(bbox_min) < 2 or len(bbox_max) < 2:
        return False
    x, y = _safe_float(point[0]), _safe_float(point[1])
    return (
        (_safe_float(bbox_min[0]) - padding) <= x <= (_safe_float(bbox_max[0]) + padding)
        and (_safe_float(bbox_min[1]) - padding) <= y <= (_safe_float(bbox_max[1]) + padding)
    )


def _expand_bbox(bbox: Dict[str, List[float]], *, x_padding: float = 0.0, y_padding: float = 0.0) -> Dict[str, List[float]]:
    bbox_min = bbox.get("min") or [0.0, 0.0]
    bbox_max = bbox.get("max") or [0.0, 0.0]
    return {
        "min": [round(_safe_float(bbox_min[0]) - x_padding, 3), round(_safe_float(bbox_min[1]) - y_padding, 3)],
        "max": [round(_safe_float(bbox_max[0]) + x_padding, 3), round(_safe_float(bbox_max[1]) + y_padding, 3)],
    }


def _bbox_area(bbox: Dict[str, List[float]]) -> float:
    bbox_min = bbox.get("min") or [0.0, 0.0]
    bbox_max = bbox.get("max") or [0.0, 0.0]
    if len(bbox_min) < 2 or len(bbox_max) < 2:
        return 0.0
    width = max(0.0, _safe_float(bbox_max[0]) - _safe_float(bbox_min[0]))
    height = max(0.0, _safe_float(bbox_max[1]) - _safe_float(bbox_min[1]))
    return width * height


def _bbox_size(bbox: Dict[str, List[float]]) -> Tuple[float, float]:
    bbox_min = bbox.get("min") or [0.0, 0.0]
    bbox_max = bbox.get("max") or [0.0, 0.0]
    if len(bbox_min) < 2 or len(bbox_max) < 2:
        return 0.0, 0.0
    return (
        max(0.0, _safe_float(bbox_max[0]) - _safe_float(bbox_min[0])),
        max(0.0, _safe_float(bbox_max[1]) - _safe_float(bbox_min[1])),
    )


def _bbox_almost_equal(
    left: Dict[str, List[float]],
    right: Dict[str, List[float]],
    *,
    tolerance: float = 2.0,
) -> bool:
    left_min = left.get("min") or [0.0, 0.0]
    left_max = left.get("max") or [0.0, 0.0]
    right_min = right.get("min") or [0.0, 0.0]
    right_max = right.get("max") or [0.0, 0.0]
    if len(left_min) < 2 or len(left_max) < 2 or len(right_min) < 2 or len(right_max) < 2:
        return False
    return (
        abs(_safe_float(left_min[0]) - _safe_float(right_min[0])) <= tolerance
        and abs(_safe_float(left_min[1]) - _safe_float(right_min[1])) <= tolerance
        and abs(_safe_float(left_max[0]) - _safe_float(right_max[0])) <= tolerance
        and abs(_safe_float(left_max[1]) - _safe_float(right_max[1])) <= tolerance
    )


def _is_axis_aligned_rect(points: Sequence[Sequence[float]]) -> bool:
    if len(points) < 4:
        return False
    xs = sorted({round(_safe_float(point[0]), 3) for point in points})
    ys = sorted({round(_safe_float(point[1]), 3) for point in points})
    return len(xs) == 2 and len(ys) == 2
