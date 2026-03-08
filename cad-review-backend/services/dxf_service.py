"""
DXF 数据提取服务
技术路线：ODA File Converter（DWG -> DXF） + ezdxf（按Layout提取JSON）
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import ezdxf

from domain.text_cleaning import strip_mtext_formatting
from services.coordinate_service import enrich_json_with_coordinates

logger = logging.getLogger(__name__)


MODEL_LAYOUT_NAMES = {
    "model",
    "modelspace",
    "model_space",
    "模型",
    "模型空间",
}

INDEX_KEYWORDS = ("索引", "INDEX", "SYMB", "SYM")
TITLE_KEYWORDS = ("图签", "TB", "TITLE", "标题")
MATERIAL_LAYER_KEYWORDS = ("MAT", "MATERIAL", "材料")


def _normalize_name(name: str) -> str:
    return re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", (name or "").strip().lower())


def _is_model_layout(name: str) -> bool:
    return _normalize_name(name) in MODEL_LAYOUT_NAMES


def _sanitize_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip("_") or "layout"


def _extract_sheet_no_from_text(text: str) -> str:
    if not text:
        return ""

    patterns = [
        r"(?<![A-Za-z])[A-Za-z]{1,3}\d{0,3}[.\-_]\d{1,3}[a-zA-Z]?(?![A-Za-z])",
        r"(?<![A-Za-z])[A-Za-z]\d{1,4}[a-zA-Z]?(?![A-Za-z])",
        r"(?<!\d)\d{2}[.\-_]\d{2}[a-zA-Z]?(?![A-Za-z])",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    upper = (text or "").upper()
    if "COVER" in upper:
        return "COVER"
    return ""


def _is_sheet_no_like(text: str) -> bool:
    if not text:
        return False
    return _extract_sheet_no_from_text(text) != ""


def _extract_sheet_name_from_layout(layout_name: str, sheet_no: str) -> str:
    if not layout_name:
        return ""
    if not sheet_no:
        return layout_name.strip()
    return layout_name.replace(sheet_no, "", 1).strip(" -_:.|")


def _is_generic_layout_name(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    normalized = _normalize_name(text)
    return bool(re.fullmatch(r"(layout|布局)\d*", normalized))


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


def _point_in_range(point: Sequence[float], model_range: Dict[str, List[float]], padding: float = 0.0) -> bool:
    if len(point) < 2:
        return False
    min_x, min_y = model_range.get("min", [0.0, 0.0])
    max_x, max_y = model_range.get("max", [0.0, 0.0])
    x, y = _safe_float(point[0]), _safe_float(point[1])
    return (min_x - padding) <= x <= (max_x + padding) and (min_y - padding) <= y <= (max_y + padding)


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


def _display_scale(scale: float) -> str:
    if scale <= 0:
        return ""
    ratio = round(1.0 / scale)
    if ratio <= 0:
        return ""
    return f"1:{ratio}"


def _extract_layout_page_range(layout) -> Dict[str, List[float]]:  # noqa: ANN001
    origin_x = _safe_float(getattr(layout.dxf, "plot_origin_x_offset", 0.0), 0.0)
    origin_y = _safe_float(getattr(layout.dxf, "plot_origin_y_offset", 0.0), 0.0)
    width = _safe_float(getattr(layout.dxf, "paper_width", 0.0), 0.0)
    height = _safe_float(getattr(layout.dxf, "paper_height", 0.0), 0.0)

    if width > 0 and height > 0:
        return {
            "min": [round(origin_x, 3), round(origin_y, 3)],
            "max": [round(origin_x + width, 3), round(origin_y + height, 3)],
        }

    min_point = _point_xy(getattr(layout.dxf, "limmin", None))
    max_point = _point_xy(getattr(layout.dxf, "limmax", None))

    if max_point[0] > min_point[0] and max_point[1] > min_point[1]:
        return {"min": min_point, "max": max_point}

    return {"min": [0.0, 0.0], "max": [0.0, 0.0]}


def _normalize_plain_text(text: str) -> str:
    return strip_mtext_formatting(text)


def _attr_list(attrs: Dict[str, str]) -> List[Dict[str, str]]:
    return [{"tag": key, "value": value} for key, value in attrs.items()]


def _is_numeric_like_text(text: str) -> bool:
    s = _normalize_plain_text(text).upper()
    if not s:
        return False
    s = s.replace("MM", "").replace(",", "").replace(" ", "")
    return bool(re.fullmatch(r"[+-]?\d+(\.\d+)?", s))


def _parse_numeric_text(text: str) -> Optional[float]:
    s = _normalize_plain_text(text).upper()
    s = s.replace("MM", "").replace(",", "").replace(" ", "")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _collect_text_entities(layout) -> List[Dict[str, Any]]:  # noqa: ANN001
    texts: List[Dict[str, Any]] = []

    for entity in layout.query("TEXT"):
        text = str(getattr(entity.dxf, "text", "") or "").strip()
        if text:
            texts.append({"text": text, "position": _point_xy(getattr(entity.dxf, "insert", None))})

    for entity in layout.query("MTEXT"):
        text = strip_mtext_formatting(str(getattr(entity, "text", "") or ""))
        if text:
            texts.append({"text": text, "position": _point_xy(getattr(entity.dxf, "insert", None))})

    return texts


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


def _infer_paper_size_hint(width: float, height: float) -> str:
    if width <= 0 or height <= 0:
        return ""
    longest = max(width, height)
    shortest = min(width, height)
    candidates = {
        "A0": (1189.0, 841.0),
        "A1": (841.0, 594.0),
        "A2": (594.0, 420.0),
        "A3": (420.0, 297.0),
        "A4": (297.0, 210.0),
    }
    for label, (ref_long, ref_short) in candidates.items():
        if abs(longest - ref_long) <= ref_long * 0.12 and abs(shortest - ref_short) <= ref_short * 0.12:
            return label
    return "custom"


def _is_axis_aligned_rect(points: Sequence[Sequence[float]]) -> bool:
    if len(points) < 4:
        return False
    xs = sorted({round(_safe_float(point[0]), 3) for point in points})
    ys = sorted({round(_safe_float(point[1]), 3) for point in points})
    return len(xs) == 2 and len(ys) == 2


def _collect_layout_frame_candidates(layout) -> List[Dict[str, Any]]:  # noqa: ANN001
    candidates: List[Dict[str, Any]] = []
    for entity in layout:
        entity_type = entity.dxftype()
        points: List[List[float]] = []

        try:
            if entity_type == "LWPOLYLINE":
                if not bool(entity.closed):
                    continue
                points = [[float(p[0]), float(p[1])] for p in entity.get_points("xy")]
            elif entity_type == "POLYLINE":
                if not bool(entity.is_closed):
                    continue
                points = [[float(vertex.dxf.location.x), float(vertex.dxf.location.y)] for vertex in entity.vertices]
            else:
                continue
        except Exception:  # noqa: BLE001
            continue

        bbox = _bbox_range(points)
        if bbox is None or not _is_axis_aligned_rect(points):
            continue

        width, height = _bbox_size(bbox)
        if width < 120.0 or height < 120.0:
            continue

        candidates.append(
            {
                "id": str(getattr(entity.dxf, "handle", "") or ""),
                "frame_bbox": bbox,
                "width": round(width, 3),
                "height": round(height, 3),
                "area": round(width * height, 3),
            }
        )

    candidates.sort(key=lambda item: item["area"], reverse=True)
    return candidates


def _object_position(item: Dict[str, Any]) -> List[float]:
    for key in ("position", "text_position", "center"):
        point = item.get(key)
        if isinstance(point, list) and len(point) >= 2:
            return [round(_safe_float(point[0]), 3), round(_safe_float(point[1]), 3)]
    return [0.0, 0.0]


def _infer_fragment_identity_from_texts(
    bbox: Dict[str, List[float]],
    text_entities: Sequence[Dict[str, Any]],
) -> Tuple[str, str]:
    width, height = _bbox_size(bbox)
    if width <= 0 or height <= 0:
        return "", ""

    candidate_bbox = _expand_bbox(bbox, x_padding=max(width * 0.08, 18.0), y_padding=max(height * 0.18, 24.0))
    lower_band_height = max(height * 0.28, 48.0)
    lower_band_downward_padding = max(height * 0.18, 24.0)
    lower_band = {
        "min": [bbox["min"][0], bbox["min"][1] - lower_band_downward_padding],
        "max": [bbox["max"][0], bbox["min"][1] + lower_band_height],
    }
    lower_band = _expand_bbox(lower_band, x_padding=max(width * 0.08, 18.0), y_padding=0.0)
    bottom_left_zone = {
        "min": [bbox["min"][0], lower_band["min"][1]],
        "max": [bbox["min"][0] + max(width * 0.42, 120.0), lower_band["max"][1]],
    }
    bottom_right_zone = {
        "min": [bbox["max"][0] - max(width * 0.42, 120.0), lower_band["min"][1]],
        "max": [bbox["max"][0], lower_band["max"][1]],
    }
    bottom_center_zone = {
        "min": [bbox["min"][0] + max(width * 0.24, 80.0), lower_band["min"][1]],
        "max": [bbox["max"][0] - max(width * 0.24, 80.0), lower_band["max"][1]],
    }

    metadata_keywords = (
        "图号",
        "图名",
        "图纸编号",
        "SHEET NO",
        "图纸标题",
        "DESCRIPTION",
        "比例",
        "SCALE",
        "修正",
        "REVISION",
        "图幅",
        "备注",
        "DRAWING CONTENTS",
        "图纸目录",
    )
    ignored_name_exact = {
        "图例",
        "说明",
        "N/A",
        "NO.",
        "SHEET NO.",
        "DESCRIPTION",
        "SCALE",
        "REVISION",
        "REMARK",
        "SHEET",
        "DRAWING CONTENTS",
        "CONSTRUCTION DRAWINGS",
    }

    best_sheet_no = ""
    best_sheet_no_score = -1.0
    best_sheet_name = ""
    best_sheet_name_score = -1.0
    selected_zone = lower_band
    zone_candidates = []
    for zone_name, zone_bbox in (
        ("left", bottom_left_zone),
        ("center", bottom_center_zone),
        ("right", bottom_right_zone),
        ("band", lower_band),
    ):
        zone_score = 0.0
        zone_text_count = 0
        for item in text_entities:
            text = strip_mtext_formatting(str(item.get("text") or "")).strip()
            position = _point_xy(item.get("position"))
            if not text or not _bbox_contains_point(zone_bbox, position):
                continue
            zone_text_count += 1
            upper_text = text.upper()
            if any(keyword in text for keyword in metadata_keywords) or any(keyword in upper_text for keyword in metadata_keywords):
                zone_score += 4.0
            if _extract_sheet_no_from_text(text):
                zone_score += 1.5
            if zone_name == "center" and ("图名" in text or "图号" in text or "DRAWING" in upper_text):
                zone_score += 0.8
        zone_score += min(zone_text_count, 12) * 0.1
        zone_candidates.append((zone_score, zone_name, zone_bbox))
    zone_candidates.sort(key=lambda item: item[0], reverse=True)
    best_zone_score = zone_candidates[0][0] if zone_candidates else 0.0
    if zone_candidates and zone_candidates[0][0] > 0:
        selected_zone = zone_candidates[0][2]
    else:
        selected_zone = lower_band

    zone_texts = []

    for item in text_entities:
        text = strip_mtext_formatting(str(item.get("text") or "")).strip()
        position = _point_xy(item.get("position"))
        if not text or not _bbox_contains_point(candidate_bbox, position):
            continue
        zone_texts.append({"text": text, "position": position})

        upper_text = text.upper()
        if any(keyword in text for keyword in ("版本", "日期")) or any(keyword in upper_text for keyword in ("VERSION", "DATE")):
            continue

        in_title_zone = _bbox_contains_point(selected_zone, position)
        in_bottom_band = _bbox_contains_point(lower_band, position)
        y_bonus = max(0.0, 1.0 - abs(position[1] - bbox["min"][1]) / max(height, 1.0))

        no_candidate = _extract_sheet_no_from_text(text)
        if no_candidate:
            normalized_candidate = no_candidate.upper()
            if normalized_candidate in {"A0", "A1", "A2", "A3", "A4"}:
                continue
            score = y_bonus + (2.5 if in_title_zone else (1.2 if in_bottom_band else 0.4))
            if score > best_sheet_no_score:
                best_sheet_no = no_candidate
                best_sheet_no_score = score
    if best_sheet_no:
        no_positions = [item["position"] for item in zone_texts if _extract_sheet_no_from_text(item["text"]) == best_sheet_no]
    else:
        no_positions = []

    for item in zone_texts:
        text = item["text"]
        position = item["position"]
        upper_text = text.upper()
        if not _bbox_contains_point(selected_zone, position):
            continue
        if _is_numeric_like_text(text) or len(text) > 48:
            continue
        if text in ignored_name_exact:
            continue
        if any(keyword in text for keyword in ("版本", "日期", "注：", "注:")):
            continue
        if any(keyword in upper_text for keyword in ("VERSION", "DATE")):
            continue
        if any(keyword in text for keyword in metadata_keywords) or any(keyword in upper_text for keyword in metadata_keywords):
            continue
        if _extract_sheet_no_from_text(text):
            continue

        has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in text)
        has_alpha = any(ch.isalpha() for ch in text)
        if not has_chinese and not has_alpha:
            continue

        score = min(len(text), 24) / 24.0
        if has_chinese:
            score += 0.8
        if "图" in text or "说明" in text or "布置" in text or "DETAIL" in upper_text:
            score += 0.6
        if no_positions:
            distance = min(_distance(position, no_pos) for no_pos in no_positions)
            min_y_delta = min(abs(position[1] - no_pos[1]) for no_pos in no_positions)
            if distance > max(width * 0.35, 120.0):
                continue
            if min_y_delta > max(height * 0.12, 28.0):
                continue
            score += max(0.0, 2.0 - (distance / max(width * 0.45, 120.0)) * 2.0)
        else:
            if best_zone_score < 4.0:
                continue
            score += max(0.0, 1.0 - abs(position[1] - bbox["min"][1]) / max(height, 1.0))
        if score > best_sheet_name_score:
            best_sheet_name = text
            best_sheet_name_score = score

    return best_sheet_no, best_sheet_name


def _detect_layout_frames(
    layout,
    *,
    layout_page_range: Dict[str, List[float]],
    title_blocks: List[Dict[str, Any]],
    detail_titles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:  # noqa: ANN001
    candidates = _collect_layout_frame_candidates(layout)
    anchors = title_blocks + detail_titles
    frames: List[Dict[str, Any]] = []
    used_ids: Set[str] = set()
    page_area = _bbox_area(layout_page_range)

    for candidate in candidates:
        bbox = candidate["frame_bbox"]
        candidate_area = _bbox_area(bbox)
        if page_area > 0 and (candidate_area / page_area) < 0.12:
            continue
        contained_anchor_count = 0
        for item in anchors:
            point = _object_position(item)
            if _bbox_contains_point(bbox, point, padding=12.0):
                contained_anchor_count += 1

        if anchors and contained_anchor_count == 0:
            continue

        duplicate = False
        for existing in frames:
            existing_bbox = existing["frame_bbox"]
            if _bbox_almost_equal(existing_bbox, bbox, tolerance=2.0):
                duplicate = True
                break
        if duplicate:
            continue

        width = candidate["width"]
        height = candidate["height"]
        frames.append(
            {
                "frame_id": candidate["id"] or f"frame-{len(frames) + 1}",
                "frame_bbox": bbox,
                "paper_size_hint": _infer_paper_size_hint(width, height),
                "orientation": "landscape" if width >= height else "portrait",
                "confidence": 1.0 if contained_anchor_count > 0 else 0.75,
            }
        )
        used_ids.add(candidate["id"])

    if frames:
        return frames

    page_width, page_height = _bbox_size(layout_page_range)
    if page_width <= 0 or page_height <= 0:
        return []

    return [
        {
            "frame_id": "frame-1",
            "frame_bbox": layout_page_range,
            "paper_size_hint": _infer_paper_size_hint(page_width, page_height),
            "orientation": "landscape" if page_width >= page_height else "portrait",
            "confidence": 0.5,
        }
    ]


def _build_layout_fragments(
    frames: List[Dict[str, Any]],
    *,
    title_blocks: List[Dict[str, Any]],
    detail_titles: List[Dict[str, Any]],
    indexes: List[Dict[str, Any]],
    dimensions: List[Dict[str, Any]],
    materials: List[Dict[str, Any]],
    viewports: List[Dict[str, Any]],
    text_entities: List[Dict[str, Any]],
    fallback_sheet_no: str,
    fallback_sheet_name: str,
    layout_name: str,
) -> List[Dict[str, Any]]:
    if not frames:
        return []

    fragments: List[Dict[str, Any]] = []
    for idx, frame in enumerate(frames, start=1):
        bbox = frame["frame_bbox"]
        fragment_title_blocks = [item for item in title_blocks if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]
        fragment_detail_titles = [item for item in detail_titles if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]
        fragment_indexes = [item for item in indexes if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]
        fragment_dimensions = [item for item in dimensions if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]
        fragment_materials = [item for item in materials if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]
        fragment_viewports = [item for item in viewports if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]

        title_sheet_no = ""
        title_sheet_name = ""
        for item in fragment_title_blocks:
            candidate_sheet_no = str(item.get("sheet_no") or "").strip()
            candidate_sheet_name = str(item.get("sheet_name") or "").strip()
            if candidate_sheet_no and not title_sheet_no:
                title_sheet_no = candidate_sheet_no
            if candidate_sheet_name and not title_sheet_name:
                title_sheet_name = candidate_sheet_name

        for item in fragment_detail_titles:
            candidate_sheet_no = str(item.get("sheet_no") or "").strip()
            if candidate_sheet_no and not title_sheet_no:
                title_sheet_no = candidate_sheet_no

        fallback_single_sheet_no = fallback_sheet_no if len(frames) == 1 else ""
        fallback_single_sheet_name = fallback_sheet_name if len(frames) == 1 else ""

        sheet_no = title_sheet_no or fallback_single_sheet_no
        sheet_name = title_sheet_name or ("" if _is_generic_layout_name(fallback_single_sheet_name) else fallback_single_sheet_name)
        if not sheet_no or not sheet_name:
            inferred_sheet_no, inferred_sheet_name = _infer_fragment_identity_from_texts(bbox, text_entities)
            if not sheet_no and inferred_sheet_no:
                sheet_no = inferred_sheet_no
            if not sheet_name and inferred_sheet_name:
                sheet_name = inferred_sheet_name

        fragments.append(
            {
                "fragment_id": f"{frame['frame_id']}-fragment-{idx}",
                "frame_id": frame["frame_id"],
                "layout_name": layout_name,
                "fragment_bbox": bbox,
                "sheet_no": sheet_no,
                "sheet_name": sheet_name,
                "scale": "",
                "title_blocks": fragment_title_blocks,
                "detail_titles": fragment_detail_titles,
                "indexes": fragment_indexes,
                "dimensions": fragment_dimensions,
                "materials": fragment_materials,
                "viewports": fragment_viewports,
                "fragment_confidence": frame.get("confidence", 0.5),
            }
        )

    return fragments


def _collect_insert_head_points(insert) -> List[List[float]]:  # noqa: ANN001
    """
    Collect visible geometry points around the callout head.

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


def get_oda_path() -> str:
    """
    获取 ODA File Converter 可执行路径。
    支持环境变量 ODA_FILE_CONVERTER_PATH 覆盖。
    """
    env_path = os.getenv("ODA_FILE_CONVERTER_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return str(candidate)

    if platform.system() == "Darwin":
        default = Path("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter")
    elif platform.system() == "Windows":
        default = Path(r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe")
    else:
        default = Path("/usr/bin/ODAFileConverter")

    if default.exists():
        return str(default)

    raise RuntimeError("请先安装ODA File Converter")


def dwg_batch_to_dxf(input_dir: str, output_dir: str) -> List[str]:
    """
    批量将 input_dir 中 DWG 转为 DXF，返回 DXF 路径列表。
    """
    in_dir = Path(input_dir).expanduser().resolve()
    out_dir = Path(output_dir).expanduser().resolve()
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    oda = get_oda_path()
    cmd = [oda, str(in_dir), str(out_dir), "ACAD2018", "DXF", "0", "1"]
    logger.info("执行ODA转换: %s", " ".join(cmd))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        raise RuntimeError(f"ODA转换失败: rc={proc.returncode}, stderr={stderr[:500]}, stdout={stdout[:500]}")

    dxf_files = sorted(
        [
            str(path.resolve())
            for path in out_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".dxf"
        ]
    )
    return dxf_files


def dwg_to_dxf(dwg_path: str, output_dir: str) -> str:
    """
    单文件DWG转DXF。
    """
    src = Path(dwg_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"DWG文件不存在: {src}")

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dwg_one_in_") as in_dir:
        copied = Path(in_dir) / src.name
        shutil.copy2(src, copied)
        dxfs = dwg_batch_to_dxf(in_dir, str(out_dir))

    stem = src.stem.lower()
    for dxf in dxfs:
        if Path(dxf).stem.lower() == stem:
            return dxf

    if not dxfs:
        raise RuntimeError("ODA转换完成但未找到DXF输出")

    return dxfs[0]


def calc_model_range(viewport) -> Dict[str, List[float]]:  # noqa: ANN001
    """
    从 VIEWPORT 计算对应模型空间范围。
    """
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
    """
    获取给定视口下可见图层集合。
    """
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


def _extract_dimensions(doc, layout, model_range: Dict[str, List[float]], visible_layers: Set[str]) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []

    def make_item(dim, source: str) -> Optional[Dict[str, Any]]:  # noqa: ANN001
        layer = str(getattr(dim.dxf, "layer", "") or "")
        if visible_layers and layer and layer not in visible_layers:
            return None

        defpoint = _point_xy(getattr(dim.dxf, "defpoint", None))
        defpoint2 = _point_xy(getattr(dim.dxf, "defpoint2", None))
        text_pos = _point_xy(
            getattr(dim.dxf, "text_midpoint", None) or getattr(dim.dxf, "defpoint", None)
        )

        if source == "model_space" and model_range and not _point_in_range(text_pos, model_range, padding=200.0):
            return None

        value = getattr(dim.dxf, "actual_measurement", None)
        if value is None:
            try:
                value = dim.get_measurement()
            except Exception:  # noqa: BLE001
                value = 0.0

        display_text = str(getattr(dim.dxf, "text", "") or "")
        if display_text in {"", "<>"}:
            display_text = str(round(_safe_float(value), 3)).rstrip("0").rstrip(".")

        return {
            "id": str(getattr(dim.dxf, "handle", "") or ""),
            "value": round(_safe_float(value), 6),
            "display_text": display_text,
            "layer": layer,
            "source": source,
            "defpoint": defpoint,
            "defpoint2": defpoint2,
            "text_position": text_pos,
        }

    for dim in doc.modelspace().query("DIMENSION"):
        item = make_item(dim, "model_space")
        if item:
            items.append(item)

    for dim in layout.query("DIMENSION"):
        item = make_item(dim, "layout_space")
        if item:
            items.append(item)

    return items


def _extract_pseudo_texts(doc, layout, model_range: Dict[str, List[float]], visible_layers: Set[str]) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []

    def collect(space, source: str) -> None:  # noqa: ANN001
        for entity in space.query("TEXT MTEXT"):
            etype = entity.dxftype()
            layer = str(getattr(entity.dxf, "layer", "") or "")
            if visible_layers and layer and layer not in visible_layers:
                continue

            if etype == "TEXT":
                raw_text = str(getattr(entity.dxf, "text", "") or "")
                pos = _point_xy(getattr(entity.dxf, "insert", None))
            else:
                raw_text = str(getattr(entity, "text", "") or "")
                pos = _point_xy(getattr(entity.dxf, "insert", None))

            text = _normalize_plain_text(raw_text)
            if not _is_numeric_like_text(text):
                continue

            if source == "model_space" and model_range and not _point_in_range(pos, model_range, padding=200.0):
                continue

            numeric_value = _parse_numeric_text(text)
            items.append(
                {
                    "id": str(getattr(entity.dxf, "handle", "") or ""),
                    "entity_type": etype,
                    "content": text,
                    "numeric_value": numeric_value if numeric_value is not None else 0.0,
                    "position": pos,
                    "layer": layer,
                    "source": source,
                }
            )

    collect(doc.modelspace(), "model_space")
    collect(layout, "layout_space")
    return items


def _looks_like_detail_label(value: str) -> bool:
    text = str(value or "").strip().upper()
    if not text:
        return False
    if len(text) > 12:
        return False
    return bool(re.fullmatch(r"[A-Z]{0,3}\d{1,4}[A-Z]{0,3}", text))


def _extract_detail_title_from_insert(
    insert,
    attrs: Dict[str, str],
    *,
    block_name: str,
    layer: str,
    position: List[float],
    source: str,
) -> Optional[Dict[str, Any]]:  # noqa: ANN001
    label = str(attrs.get("DN") or attrs.get("TITLELABEL") or attrs.get("TITLE_LABEL") or "").strip()
    if not _looks_like_detail_label(label):
        return None

    title_lines = [
        str(attrs.get(key) or "").strip()
        for key in ("TITLE1", "TITLE2", "TITLE3")
        if str(attrs.get(key) or "").strip()
    ]
    if not title_lines and "TITLE" in block_name.upper():
        title_lines = []
    if not title_lines and "G-ANNO-TITL" not in layer.upper():
        return None

    return {
        "id": str(getattr(insert.dxf, "handle", "") or ""),
        "label": label,
        "sheet_no": str(attrs.get("SHEETNO") or attrs.get("DRAWINGNO") or attrs.get("DRAWNO") or "").strip(),
        "title_lines": title_lines,
        "title_text": " ".join(title_lines).strip(),
        "block_name": block_name,
        "layer": layer,
        "attrs": _attr_list(attrs),
        "position": position,
        "source": source,
        "semantic_type": "detail_title",
    }


def _collect_detail_titles_from_space(
    space,
    *,
    source: str,
    model_range: Dict[str, List[float]],
    visible_layers: Set[str],
) -> List[Dict[str, Any]]:  # noqa: ANN001
    detail_titles: List[Dict[str, Any]] = []

    for insert in space.query("INSERT"):
        block_name = str(getattr(insert.dxf, "name", "") or "")
        layer = str(getattr(insert.dxf, "layer", "") or "")
        if visible_layers and layer and layer not in visible_layers:
            continue

        position = _point_xy(getattr(insert.dxf, "insert", None))
        if source == "model_space" and model_range and not _point_in_range(position, model_range, padding=200.0):
            continue

        attrs: Dict[str, str] = {}
        for attrib in getattr(insert, "attribs", []):
            tag = str(getattr(attrib.dxf, "tag", "") or "").upper().strip()
            text = str(getattr(attrib.dxf, "text", "") or "").strip()
            if tag:
                attrs[tag] = text

        detail_title = _extract_detail_title_from_insert(
            insert,
            attrs,
            block_name=block_name,
            layer=layer,
            position=position,
            source=source,
        )
        if detail_title:
            detail_titles.append(detail_title)

    return detail_titles


def _extract_insert_info(
    doc,
    layout,
    model_range: Dict[str, List[float]],
    visible_layers: Set[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], str, str]:  # noqa: ANN001
    indexes: List[Dict[str, Any]] = []
    title_blocks: List[Dict[str, Any]] = []
    detail_titles: List[Dict[str, Any]] = []
    first_sheet_no = ""
    first_sheet_name = ""

    for insert in layout.query("INSERT"):
        block_name = str(getattr(insert.dxf, "name", "") or "")
        upper_name = block_name.upper()
        layer = str(getattr(insert.dxf, "layer", "") or "")
        position = _point_xy(getattr(insert.dxf, "insert", None))

        attrs: Dict[str, str] = {}
        for attrib in getattr(insert, "attribs", []):
            tag = str(getattr(attrib.dxf, "tag", "") or "").upper().strip()
            text = str(getattr(attrib.dxf, "text", "") or "").strip()
            if tag:
                attrs[tag] = text

        index_no_keys = (
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
        )
        target_sheet_keys = (
            "_ACM-SHEETNUMBER",
            "SHT",
            "SHEET",
            "TARGET",
            "图号",
            "DRAWINGNO",
            "DRAWNO",
            "SHEETNO",
        )
        title_no_keys = ("图号", "DRAWNO", "DRAWINGNO", "SHEETNO")
        title_name_keys = ("图名", "DRAWNAME", "SHEETNAME", "_ACM-TITLEMARK")

        def pick_attr(keys) -> str:  # noqa: ANN001
            for key in keys:
                if attrs.get(key):
                    return attrs[key]
            return ""

        idx_no_candidate = pick_attr(index_no_keys)
        target_candidate = pick_attr(target_sheet_keys)

        # 常见索引写法：REF# + SHT / _ACM-CALLOUTNUMBER + _ACM-SHEETNUMBER
        has_index_pair = bool(idx_no_candidate and target_candidate)
        has_index_tag = any(any(keyword in key for keyword in INDEX_KEYWORDS) for key in attrs)
        has_callout_tag = any(key in attrs for key in ("_ACM-CALLOUTNUMBER", "_ACM-SECTIONLABEL", "REF#"))
        has_sheet_ref_tag = any(key in attrs for key in ("_ACM-SHEETNUMBER", "SHT", "SHEET", "SHEETNO"))

        is_index = (
            any(keyword in upper_name for keyword in INDEX_KEYWORDS)
            or has_index_tag
            or has_index_pair
            or (has_callout_tag and has_sheet_ref_tag)
        )

        is_title = (
            any(keyword in upper_name for keyword in TITLE_KEYWORDS)
            or any(key in attrs for key in ("_ACM-TITLELABEL", "_ACM-TITLEMARK", "_ACM-VPSCALE"))
            or any(key in attrs for key in title_no_keys + title_name_keys)
        )

        if is_index:
            index_no = idx_no_candidate
            target_sheet = target_candidate
            visual_anchor, anchor_source = _estimate_index_anchor(insert)
            symbol_bbox = _estimate_insert_visual_bbox(insert)
            indexes.append(
                {
                    "id": str(getattr(insert.dxf, "handle", "") or ""),
                    "block_name": block_name,
                    "index_no": index_no,
                    "target_sheet": target_sheet,
                    "source": "layout_space",
                    "position": visual_anchor,
                    "insert_position": position,
                    "anchor_source": anchor_source,
                    "symbol_bbox": symbol_bbox,
                    "layer": layer,
                    "attrs": _attr_list(attrs),
                }
            )

        if is_title:
            sheet_no = pick_attr(title_no_keys)
            sheet_name = pick_attr(title_name_keys)

            if not first_sheet_no and sheet_no:
                first_sheet_no = sheet_no
            if not first_sheet_name and sheet_name:
                first_sheet_name = sheet_name

            title_blocks.append(
                {
                    "id": str(getattr(insert.dxf, "handle", "") or ""),
                    "block_name": block_name,
                    "sheet_no": sheet_no,
                    "sheet_name": sheet_name,
                    "position": position,
                    "layer": layer,
                    "attrs": _attr_list(attrs),
                }
            )

    detail_titles.extend(
        _collect_detail_titles_from_space(
            doc.modelspace(),
            source="model_space",
            model_range=model_range,
            visible_layers=visible_layers,
        )
    )
    detail_titles.extend(
        _collect_detail_titles_from_space(
            layout,
            source="layout_space",
            model_range=model_range,
            visible_layers=visible_layers,
        )
    )

    return indexes, title_blocks, detail_titles, first_sheet_no, first_sheet_name


def _extract_materials(layout) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    text_entities = _collect_text_entities(layout)

    try:
        ml_entities = list(layout.query("MLEADER"))
    except Exception:  # noqa: BLE001
        ml_entities = []

    try:
        ml_entities += list(layout.query("MULTILEADER"))
    except Exception:  # noqa: BLE001
        pass

    for ml in ml_entities:
        layer = str(getattr(ml.dxf, "layer", "") or "")
        content = ""
        if hasattr(ml, "get_mtext_content"):
            try:
                content = str(ml.get_mtext_content() or "")
            except Exception:  # noqa: BLE001
                content = ""
        if not content:
            content = str(getattr(ml.dxf, "text", "") or "")
        content = strip_mtext_formatting(content)

        arrow = _point_xy(
            getattr(ml.dxf, "insert", None)
            or getattr(ml.dxf, "base_point", None)
            or getattr(ml.dxf, "arrow_head", None)
        )

        token = content.split()[0] if content else ""
        code = token if token and re.search(r"\d", token) else ""

        if content or any(keyword in layer.upper() for keyword in MATERIAL_LAYER_KEYWORDS):
            items.append(
                {
                    "id": str(getattr(ml.dxf, "handle", "") or ""),
                    "entity_type": "MLEADER",
                    "content": content,
                    "code": code,
                    "position": arrow,
                    "arrow": arrow,
                    "layer": layer,
                }
            )

    for leader in layout.query("LEADER"):
        layer = str(getattr(leader.dxf, "layer", "") or "")
        vertices = []
        if hasattr(leader, "vertices"):
            try:
                vertices = [
                    _point_xy(point)
                    for point in leader.vertices()  # pyright: ignore[reportCallIssue]
                ]
            except Exception:  # noqa: BLE001
                vertices = []

        arrow = vertices[0] if vertices else _point_xy(getattr(leader.dxf, "insert", None))

        nearest_text = ""
        nearest_dist = 1e9
        for text_obj in text_entities:
            dist = _distance(arrow, text_obj["position"])
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_text = text_obj["text"]

        if nearest_dist > 50.0:
            nearest_text = ""

        token = nearest_text.strip().split()[0] if nearest_text.strip() else ""
        code = token if token and re.search(r"\d", token) else ""

        if nearest_text or any(keyword in layer.upper() for keyword in MATERIAL_LAYER_KEYWORDS):
            items.append(
                {
                    "id": str(getattr(leader.dxf, "handle", "") or ""),
                    "entity_type": "LEADER",
                    "content": nearest_text,
                    "code": code,
                    "position": arrow,
                    "arrow": arrow,
                    "layer": layer,
                }
            )

    return items


def _pair_material_rows_from_text(layout) -> List[Dict[str, str]]:  # noqa: ANN001
    texts = _collect_text_entities(layout)
    if not texts:
        return []

    # 先按Y聚类，再在行内按X排序，做 code+name 拼合
    texts_sorted = sorted(texts, key=lambda item: (-item["position"][1], item["position"][0]))

    rows: List[List[Dict[str, Any]]] = []
    row_tol = 30.0
    for item in texts_sorted:
        if not rows:
            rows.append([item])
            continue

        row_y = rows[-1][0]["position"][1]
        if abs(item["position"][1] - row_y) <= row_tol:
            rows[-1].append(item)
        else:
            rows.append([item])

    pairs: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        row_sorted = sorted(row, key=lambda item: item["position"][0])
        line = " ".join(item["text"] for item in row_sorted).strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue

        code = parts[0].strip()
        name = " ".join(parts[1:]).strip()
        if not re.search(r"\d", code) or not name:
            continue

        key = (code.upper(), name.upper())
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"code": code, "name": name})

    return pairs


def _extract_material_table(layout) -> List[Dict[str, str]]:  # noqa: ANN001
    rows: List[Dict[str, str]] = []
    seen = set()

    for table in layout.query("TABLE"):
        n_rows = int(_safe_float(getattr(table, "n_rows", 0), 0.0))
        n_cols = int(_safe_float(getattr(table, "n_cols", 0), 0.0))

        if n_rows <= 0 or n_cols <= 0:
            # 兜底走文本拼合
            continue

        for ridx in range(n_rows):
            try:
                c0 = strip_mtext_formatting(str(table.get_cell_text(ridx, 0) or ""))
            except Exception:  # noqa: BLE001
                c0 = ""
            try:
                c1 = strip_mtext_formatting(str(table.get_cell_text(ridx, 1) or "")) if n_cols > 1 else ""
            except Exception:  # noqa: BLE001
                c1 = ""

            if not re.search(r"\d", c0) or not c1:
                continue

            key = (c0.upper(), c1.upper())
            if key in seen:
                continue
            seen.add(key)
            rows.append({"code": c0, "name": c1})

    if rows:
        return rows

    return _pair_material_rows_from_text(layout)


def _collect_viewports(layout, model_range: Dict[str, List[float]], active_layer: str) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    for vp in layout.query("VIEWPORT"):
        vp_id = int(_safe_float(getattr(vp.dxf, "id", 0), 0.0))
        if vp_id == 1:
            continue

        center = _point_xy(getattr(vp.dxf, "center", None))
        scale = _safe_float(getattr(vp.dxf, "scale", 0.0), 0.0)
        vp_model_range = calc_model_range(vp)
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
                "frozen_layers": [],
                "model_range": vp_model_range if vp_model_range.get("max") != vp_model_range.get("min") else model_range,
            }
        )
    return items


def extract_layout(doc, layout_name: str, dwg_filename: str) -> Optional[Dict[str, Any]]:  # noqa: ANN001
    """
    按单个 Layout 提取 JSON 数据。
    """
    if _is_model_layout(layout_name):
        return None

    try:
        layout = doc.layouts.get(layout_name)
    except Exception:  # noqa: BLE001
        return None

    if layout is None:
        return None

    main_vp = _pick_main_viewport(layout)

    if main_vp is not None:
        model_range = calc_model_range(main_vp)
        visible_layers = get_visible_layers(doc, main_vp)
        if hasattr(main_vp, "get_scale"):
            try:
                scale = _safe_float(main_vp.get_scale(), 0.0)
            except Exception:  # noqa: BLE001
                scale = _safe_float(getattr(main_vp.dxf, "scale", 0.0), 0.0)
        else:
            scale = _safe_float(getattr(main_vp.dxf, "scale", 0.0), 0.0)
    else:
        model_range = {"min": [0.0, 0.0], "max": [0.0, 0.0]}
        visible_layers = {str(getattr(layer.dxf, "name", "") or "") for layer in doc.layers if not layer.is_off()}
        scale = 0.0

    dimensions = _extract_dimensions(doc, layout, model_range, visible_layers)
    pseudo_texts = _extract_pseudo_texts(doc, layout, model_range, visible_layers)
    indexes, title_blocks, detail_titles, title_sheet_no, title_sheet_name = _extract_insert_info(
        doc,
        layout,
        model_range,
        visible_layers,
    )
    materials = _extract_materials(layout)
    material_table = _extract_material_table(layout)
    layers = _collect_layer_states(doc)
    layout_page_range = _extract_layout_page_range(layout)
    text_entities = _collect_text_entities(layout)

    title_no = (title_sheet_no or "").strip()
    layout_no = _extract_sheet_no_from_text(layout_name)
    dwg_no = _extract_sheet_no_from_text(dwg_filename)
    sheet_no = title_no if _is_sheet_no_like(title_no) else (layout_no or dwg_no)
    sheet_name = title_sheet_name or _extract_sheet_name_from_layout(layout_name, sheet_no)

    active_layer = str(getattr(doc.header, "$CLAYER", "") or "")
    viewports = _collect_viewports(layout, model_range, active_layer)
    layout_frames = _detect_layout_frames(
        layout,
        layout_page_range=layout_page_range,
        title_blocks=title_blocks,
        detail_titles=detail_titles,
    )
    layout_fragments = _build_layout_fragments(
        layout_frames,
        title_blocks=title_blocks,
        detail_titles=detail_titles,
        indexes=indexes,
        dimensions=dimensions,
        materials=materials,
        viewports=viewports,
        text_entities=text_entities,
        fallback_sheet_no=sheet_no,
        fallback_sheet_name=sheet_name,
        layout_name=layout_name,
    )

    payload: Dict[str, Any] = {
        "source_dwg": dwg_filename,
        "layout_name": layout_name,
        "sheet_no": sheet_no,
        "sheet_name": sheet_name,
        "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_version": 1,
        "scale": _display_scale(scale),
        "model_range": model_range,
        "layout_page_range": layout_page_range,
        "layout_frames": layout_frames,
        "layout_fragments": layout_fragments,
        "is_multi_sheet_layout": len(layout_fragments) > 1,
        "viewports": viewports,
        "dimensions": dimensions,
        "pseudo_texts": pseudo_texts,
        "indexes": indexes,
        "title_blocks": title_blocks,
        "detail_titles": detail_titles,
        "materials": materials,
        "material_table": material_table,
        "layers": layers,
    }

    return enrich_json_with_coordinates(payload)


@lru_cache(maxsize=64)
def _cached_layout_page_range(dwg_path: str, layout_name: str, mtime: float) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    del mtime
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    with tempfile.TemporaryDirectory(prefix="ccad-layout-range-") as tmp_root:
        tmp_root_path = Path(tmp_root)
        input_dir = tmp_root_path / "in"
        output_dir = tmp_root_path / "out"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied = input_dir / source_path.name
        shutil.copy2(source_path, copied)

        dxf_files = dwg_batch_to_dxf(str(input_dir), str(output_dir))
        if not dxf_files:
            return None

        doc = ezdxf.readfile(dxf_files[0])
        try:
            layout = doc.layouts.get(layout_name)
        except Exception:  # noqa: BLE001
            return None
        if layout is None:
            return None

        page_range = _extract_layout_page_range(layout)
        mn = page_range.get("min", [0.0, 0.0])
        mx = page_range.get("max", [0.0, 0.0])
        if len(mn) < 2 or len(mx) < 2:
            return None
        if mx[0] <= mn[0] or mx[1] <= mn[1]:
            return None
        return ((float(mn[0]), float(mn[1])), (float(mx[0]), float(mx[1])))


def read_layout_page_range_from_dwg(dwg_path: str, layout_name: str) -> Optional[Dict[str, List[float]]]:
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    try:
        cached = _cached_layout_page_range(str(source_path), layout_name, source_path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None
    if cached is None:
        return None

    mn, mx = cached
    return {
        "min": [round(mn[0], 3), round(mn[1], 3)],
        "max": [round(mx[0], 3), round(mx[1], 3)],
    }


@lru_cache(maxsize=64)
def _cached_layout_indexes(
    dwg_path: str,
    layout_name: str,
    mtime: float,
) -> Optional[Tuple[Tuple[str, str, Tuple[float, float], Tuple[float, float]], ...]]:
    del mtime
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    with tempfile.TemporaryDirectory(prefix="ccad-layout-indexes-") as tmp_root:
        tmp_root_path = Path(tmp_root)
        input_dir = tmp_root_path / "in"
        output_dir = tmp_root_path / "out"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied = input_dir / source_path.name
        shutil.copy2(source_path, copied)

        dxf_files = dwg_batch_to_dxf(str(input_dir), str(output_dir))
        if not dxf_files:
            return None

        doc = ezdxf.readfile(dxf_files[0])
        payload = extract_layout(doc, layout_name, source_path.name)
        if not payload:
            return None

        items: List[Tuple[str, str, Tuple[float, float], Tuple[float, float], str, Tuple[float, float], Tuple[float, float]]] = []
        for index in payload.get("indexes", []) or []:
            position = index.get("position")
            insert_position = index.get("insert_position") or position
            symbol_bbox = index.get("symbol_bbox") or {}
            bbox_min = symbol_bbox.get("min")
            bbox_max = symbol_bbox.get("max")
            if not isinstance(position, list) or len(position) < 2:
                continue
            if not isinstance(insert_position, list) or len(insert_position) < 2:
                continue
            if not isinstance(bbox_min, list) or len(bbox_min) < 2 or not isinstance(bbox_max, list) or len(bbox_max) < 2:
                bbox_min = position
                bbox_max = position
            items.append(
                (
                    str(index.get("index_no") or "").strip(),
                    str(index.get("target_sheet") or "").strip(),
                    (float(position[0]), float(position[1])),
                    (float(insert_position[0]), float(insert_position[1])),
                    str(index.get("anchor_source") or "").strip(),
                    (float(bbox_min[0]), float(bbox_min[1])),
                    (float(bbox_max[0]), float(bbox_max[1])),
                )
            )
        return tuple(items)


def read_layout_indexes_from_dwg(dwg_path: str, layout_name: str) -> Optional[List[Dict[str, Any]]]:
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    try:
        cached = _cached_layout_indexes(str(source_path), layout_name, source_path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None
    if cached is None:
        return None

    indexes: List[Dict[str, Any]] = []
    for index_no, target_sheet, position, insert_position, anchor_source, bbox_min, bbox_max in cached:
        indexes.append(
            {
                "index_no": index_no,
                "target_sheet": target_sheet,
                "position": [round(position[0], 3), round(position[1], 3)],
                "insert_position": [round(insert_position[0], 3), round(insert_position[1], 3)],
                "anchor_source": anchor_source,
                "symbol_bbox": {
                    "min": [round(bbox_min[0], 3), round(bbox_min[1], 3)],
                    "max": [round(bbox_max[0], 3), round(bbox_max[1], 3)],
                },
            }
        )
    return indexes


@lru_cache(maxsize=64)
def _cached_layout_detail_titles(
    dwg_path: str,
    layout_name: str,
    mtime: float,
) -> Optional[Tuple[Tuple[str, str, str, str, Tuple[float, float], str], ...]]:
    del mtime
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    with tempfile.TemporaryDirectory(prefix="ccad-layout-detail-titles-") as tmp_root:
        tmp_root_path = Path(tmp_root)
        input_dir = tmp_root_path / "in"
        output_dir = tmp_root_path / "out"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied = input_dir / source_path.name
        shutil.copy2(source_path, copied)

        dxf_files = dwg_batch_to_dxf(str(input_dir), str(output_dir))
        if not dxf_files:
            return None

        doc = ezdxf.readfile(dxf_files[0])
        payload = extract_layout(doc, layout_name, source_path.name)
        if not payload:
            return None

        items: List[Tuple[str, str, str, str, Tuple[float, float], str]] = []
        for item in payload.get("detail_titles", []) or []:
            position = item.get("position")
            if not isinstance(position, list) or len(position) < 2:
                continue
            items.append(
                (
                    str(item.get("label") or "").strip(),
                    str(item.get("sheet_no") or "").strip(),
                    str(item.get("title_text") or "").strip(),
                    str(item.get("block_name") or "").strip(),
                    (float(position[0]), float(position[1])),
                    str(item.get("source") or "").strip(),
                )
            )
        return tuple(items)


def read_layout_detail_titles_from_dwg(dwg_path: str, layout_name: str) -> Optional[List[Dict[str, Any]]]:
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    try:
        cached = _cached_layout_detail_titles(str(source_path), layout_name, source_path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None
    if cached is None:
        return None

    detail_titles: List[Dict[str, Any]] = []
    for label, sheet_no, title_text, block_name, position, source in cached:
        detail_titles.append(
            {
                "label": label,
                "sheet_no": sheet_no,
                "title_text": title_text,
                "title_lines": [title_text] if title_text else [],
                "block_name": block_name,
                "position": [round(position[0], 3), round(position[1], 3)],
                "source": source,
            }
        )
    return detail_titles


def read_layout_structure_from_dwg(dwg_path: str, layout_name: str) -> Optional[Dict[str, Any]]:
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    with tempfile.TemporaryDirectory(prefix="ccad-layout-structure-") as tmp_root:
        tmp_root_path = Path(tmp_root)
        input_dir = tmp_root_path / "in"
        output_dir = tmp_root_path / "out"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied = input_dir / source_path.name
        shutil.copy2(source_path, copied)

        dxf_files = dwg_batch_to_dxf(str(input_dir), str(output_dir))
        if not dxf_files:
            return None

        doc = ezdxf.readfile(dxf_files[0])
        payload = extract_layout(doc, layout_name, source_path.name)
        if not payload:
            return None

        return {
            "sheet_no": payload.get("sheet_no"),
            "sheet_name": payload.get("sheet_name"),
            "layout_frames": payload.get("layout_frames") or [],
            "layout_fragments": payload.get("layout_fragments") or [],
            "is_multi_sheet_layout": bool(payload.get("is_multi_sheet_layout")),
        }


def _write_layout_json(output_dir: Path, dwg_stem: str, layout_payload: Dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{_sanitize_filename(dwg_stem)}_{_sanitize_filename(layout_payload.get('layout_name', 'layout'))}.json"
    path = output_dir / file_name
    path.write_text(json.dumps(layout_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _list_dwg_paths(paths: Iterable[str]) -> List[Path]:
    out = []
    for item in paths:
        path = Path(str(item)).expanduser().resolve()
        if path.exists() and path.suffix.lower() == ".dwg":
            out.append(path)
    return out


def process_dwg_files(
    dwg_paths: Sequence[str],
    project_id: str,
    output_dir: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """
    批量处理DWG：ODA批量转DXF + ezdxf按布局提取JSON。

    返回：
    [
      {
        'dwg_path': '/abs/a.dwg',
        'dwg': 'a.dwg',
        'layout_name': '平面布置图',
        'sheet_no': 'A1-01',
        'sheet_name': '平面布置图',
        'json_path': '/abs/out/a_平面布置图.json',
        'data': {...}
      }
    ]
    """
    resolved_dwgs = _list_dwg_paths(dwg_paths)
    if not resolved_dwgs:
        return []

    try:
        import ezdxf  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"缺少ezdxf依赖，请安装后重试: {exc}") from exc

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="ccad_dwg_in_") as tmp_in, tempfile.TemporaryDirectory(
        prefix="ccad_dxf_out_"
    ) as tmp_out:
        tmp_in_path = Path(tmp_in)
        tmp_out_path = Path(tmp_out)

        for dwg in resolved_dwgs:
            shutil.copy2(dwg, tmp_in_path / dwg.name)

        dxf_paths = dwg_batch_to_dxf(str(tmp_in_path), str(tmp_out_path))
        dxf_by_stem = {Path(path).stem.lower(): path for path in dxf_paths}

        # 先统计总布局数，便于前端进度
        total_layouts = 0
        docs_cache: List[Tuple[Path, Any]] = []
        for dwg in resolved_dwgs:
            dxf_path = dxf_by_stem.get(dwg.stem.lower())
            if not dxf_path:
                logger.warning("未找到DWG对应DXF: %s", str(dwg))
                continue

            doc = ezdxf.readfile(dxf_path)
            docs_cache.append((dwg, doc))
            for layout in doc.layouts:
                if not _is_model_layout(layout.name):
                    total_layouts += 1

        done = 0
        for dwg, doc in docs_cache:
            for layout in doc.layouts:
                layout_name = layout.name
                if _is_model_layout(layout_name):
                    continue

                layout_payload = extract_layout(doc, layout_name, dwg.name)
                if not layout_payload:
                    continue

                json_path = _write_layout_json(out_dir, dwg.stem, layout_payload)
                done += 1

                record = {
                    "dwg_path": str(dwg),
                    "dwg": dwg.name,
                    "layout_name": layout_payload.get("layout_name", layout_name),
                    "sheet_no": layout_payload.get("sheet_no", ""),
                    "sheet_name": layout_payload.get("sheet_name", ""),
                    "json_path": json_path,
                    "data": layout_payload,
                }
                results.append(record)

                if progress_callback:
                    try:
                        progress_callback(
                            {
                                "type": "dwg_progress",
                                "project_id": project_id,
                                "dwg": dwg.name,
                                "layout": layout_name,
                                "done": done,
                                "total": total_layouts,
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("DWG进度回调异常: %s", str(exc))

    return results
