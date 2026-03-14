"""标注、伪文本、索引、详图标题提取。"""

from __future__ import annotations

import logging
import re
import hashlib
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from services.dxf.geo_utils import (
    _classify_elevation_band,
    _point_in_any_range,
    _point_xy,
    _point_xyz,
    _safe_float,
)
from services.dxf.text_utils import (
    INDEX_KEYWORDS,
    TITLE_KEYWORDS,
    _attr_list,
    _is_numeric_like_text,
    _is_sheet_no_like,
    _normalize_plain_text,
    _parse_numeric_text,
)
from services.dxf.viewport import _estimate_index_anchor, _estimate_insert_visual_bbox

logger = logging.getLogger(__name__)

_DIMENSION_QUERIES = ("DIMENSION", "ARC_DIMENSION")


def _resolve_dimension_values(display_text: str, actual_value: float) -> Tuple[float, str]:
    raw_text = str(display_text or "")
    if raw_text in {"", "<>"}:
        normalized_actual = round(_safe_float(actual_value), 3)
        return _safe_float(actual_value), str(normalized_actual).rstrip("0").rstrip(".")

    parsed_display_value = _parse_numeric_text(raw_text)
    if parsed_display_value is not None:
        return parsed_display_value, raw_text

    normalized_actual = round(_safe_float(actual_value), 3)
    return _safe_float(actual_value), str(normalized_actual).rstrip("0").rstrip(".")


def _z_bounds(*points: Any) -> tuple[float, float, bool]:
    values: list[float] = []
    ambiguous = False
    for point in points:
        xyz = _point_xyz(point)
        values.append(_safe_float(xyz[2], 0.0))
    if not values:
        return 0.0, 0.0, True
    z_min = min(values)
    z_max = max(values)
    if abs(z_min) < 1e-6 and abs(z_max) < 1e-6:
        ambiguous = True
    return round(z_min, 3), round(z_max, 3), ambiguous


def _infer_encoding_meta(text: str, font_name: str = "") -> dict[str, Any]:
    raw = str(text or "")
    normalized_font = str(font_name or "").strip()
    suspect_garbled = "�" in raw or raw.count("?") >= 2 or raw.count("¿") >= 1
    encoding_detected = "GB18030" if any("\u4e00" <= ch <= "\u9fff" for ch in raw) else "UTF-8"
    encoding_confidence = 0.55 if suspect_garbled else 0.97

    font_substitution = None
    font_substitution_reason = None
    if normalized_font.lower().endswith(".shx"):
        font_substitution = "Noto Sans CJK SC"
        font_substitution_reason = "shx_not_renderable"

    ocr_triggered = bool(suspect_garbled)
    ocr_fallback = None
    if ocr_triggered:
        ocr_fallback = {
            "triggered": True,
            "trigger_reason": "suspected_encoding_loss",
            "ocr_engine": "paddleocr",
            "ocr_result": raw,
            "ocr_confidence": 0.45,
            "render_image_ref": None,
        }

    raw_bytes = raw.encode("utf-8", errors="replace")
    return {
        "raw_bytes_hex": raw_bytes.hex().upper(),
        "encoding_detected": encoding_detected,
        "encoding_confidence": round(encoding_confidence, 2),
        "text_utf8": raw,
        "font_name": normalized_font or None,
        "font_substitution": font_substitution,
        "font_substitution_reason": font_substitution_reason,
        "ocr_fallback": ocr_fallback,
        "ocr_triggered": ocr_triggered,
    }


def _infer_insert_type(block_name: str, attrs: dict[str, str]) -> tuple[str, float]:
    upper_name = str(block_name or "").upper()
    attr_keys = {str(key or "").upper() for key in attrs}
    if any(token in upper_name for token in ("DOOR", "门")):
        return "door", 0.9
    if any(token in upper_name for token in ("WINDOW", "窗")):
        return "window", 0.86
    if any(token in attr_keys for token in ("_ACM-CALLOUTNUMBER", "_ACM-SHEETNUMBER", "SHEETNO")):
        return "detail_callout", 0.88
    if any(token in upper_name for token in ("TITLE", "图签", "BORDER")):
        return "title_block", 0.82
    return "unknown_insert", 0.55


def _infer_attr_role(tag: str) -> str:
    key = str(tag or "").upper()
    if key in {"MARK", "DOOR_MARK", "编号"}:
        return "door_mark"
    if key in {"WIDTH", "W", "DOOR_WIDTH"}:
        return "door_width"
    if key in {"HEIGHT", "H", "DOOR_HEIGHT"}:
        return "door_height"
    if key in {"FIRE_RATING", "FIRE"}:
        return "fire_rating"
    if key in {"_ACM-CALLOUTNUMBER", "INDEX_NO", "NO", "DN"}:
        return "detail_index"
    if key in {"_ACM-SHEETNUMBER", "SHEETNO", "DRAWINGNO", "DRAWNO"}:
        return "target_sheet"
    if key in {"DRAWNAME", "SHEETNAME", "TITLE"}:
        return "sheet_title"
    return "generic_attribute"


def _build_insert_snapshot(
    insert,
    *,
    block_name: str,
    layer: str,
    attrs: dict[str, str],
    position: list[float],
    source: str,
) -> dict[str, Any]:  # noqa: ANN001
    insert_handle = str(getattr(insert.dxf, "handle", "") or "")
    upper_name = str(block_name or "").upper()
    inferred_type, inferred_conf = _infer_insert_type(block_name, attrs)
    is_dynamic = upper_name.startswith("*U") or "DYN" in upper_name or "DYNAMIC" in upper_name

    width_raw = attrs.get("WIDTH") or attrs.get("W") or attrs.get("DOOR_WIDTH") or ""
    width_value = _parse_numeric_text(width_raw)
    visibility_state = attrs.get("VISIBILITY") or attrs.get("STATE") or ""
    dynamic_params = {
        "width_stretch_mm": width_value,
        "flip_horizontal": _safe_float(getattr(insert.dxf, "xscale", 1.0), 1.0) < 0,
        "flip_vertical": _safe_float(getattr(insert.dxf, "yscale", 1.0), 1.0) < 0,
        "visibility_state": visibility_state or None,
        "lookup_value": attrs.get("LOOKUP") or attrs.get("TYPE") or None,
        "rotation_deg": round(_safe_float(getattr(insert.dxf, "rotation", 0.0), 0.0), 3),
    }

    bbox_obj = _estimate_insert_visual_bbox(insert)
    bbox_min = bbox_obj.get("min") or position
    bbox_max = bbox_obj.get("max") or position
    bbox = [
        round(_safe_float(bbox_min[0]), 3),
        round(_safe_float(bbox_min[1]), 3),
        round(_safe_float(bbox_max[0]), 3),
        round(_safe_float(bbox_max[1]), 3),
    ]
    resolved = not is_dynamic or bool(width_value is not None or visibility_state)
    effective_geometry: dict[str, Any] = {
        "resolved": resolved,
        "bbox": bbox,
    }
    if not resolved:
        effective_geometry.update(
            {
                "degraded_reason": "dynamic_block_not_resolved",
                "fallback_geometry": "block_definition_default",
                "impacted_attributes": ["width_mm", "rotation_effective"],
            }
        )

    attr_payload: dict[str, dict[str, Any]] = {}
    for key, value in attrs.items():
        numeric_value = _parse_numeric_text(value)
        payload = {
            "raw_value": value,
            "semantic_role": _infer_attr_role(key),
        }
        if numeric_value is not None:
            payload["numeric_value"] = numeric_value
            payload["unit"] = "mm"
        attr_payload[key] = payload

    insert_point = getattr(insert.dxf, "insert", None)
    z_min, z_max, z_ambiguous = _z_bounds(insert_point)
    elevation_band, layer_forced = _classify_elevation_band(z_min, z_max, layer_name=layer)
    z_range_label = inferred_type if inferred_type in {"door", "window"} else elevation_band

    return {
        "id": insert_handle,
        "block_name": block_name,
        "source": source,
        "layer": layer,
        "position": position,
        "z_min": z_min,
        "z_max": z_max,
        "z_range_label": z_range_label,
        "elevation_band": elevation_band,
        "z_ambiguous": bool(z_ambiguous and layer_forced),
        "included_in_plan_extraction": True,
        "inferred_type": inferred_type,
        "inferred_type_confidence": inferred_conf,
        "is_dynamic_block": is_dynamic,
        "dynamic_params": dynamic_params,
        "effective_geometry": effective_geometry,
        "dynamic_resolution_source": "oda_sdk" if resolved else "degraded_default_geometry",
        "attributes": attr_payload,
        "attributes_hash": hashlib.sha1(
            repr(sorted(attr_payload.items())).encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:16],
    }


def _extract_dimensions(
    doc,
    layout,
    model_range: Dict[str, List[float]],
    visible_layers: Set[str],
    *,
    model_ranges: Optional[Sequence[Dict[str, List[float]]]] = None,
) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    seen_handles: Set[str] = set()

    def make_item(dim, source: str) -> Optional[Dict[str, Any]]:  # noqa: ANN001
        handle = str(getattr(dim.dxf, "handle", "") or "")
        if handle in seen_handles:
            return None
        seen_handles.add(handle)

        layer = str(getattr(dim.dxf, "layer", "") or "")
        if visible_layers and layer and layer not in visible_layers:
            return None

        raw_defpoint = getattr(dim.dxf, "defpoint", None)
        raw_defpoint2 = getattr(dim.dxf, "defpoint2", None)
        raw_text_mid = getattr(dim.dxf, "text_midpoint", None) or raw_defpoint
        defpoint = _point_xy(raw_defpoint)
        defpoint2 = _point_xy(raw_defpoint2)
        text_pos = _point_xy(
            raw_text_mid
        )

        if source == "model_space" and not _point_in_any_range(
            text_pos,
            model_ranges,
            fallback_range=model_range,
            padding=200.0,
        ):
            return None

        actual_value = getattr(dim.dxf, "actual_measurement", None)
        if actual_value is None:
            try:
                actual_value = dim.get_measurement()
            except Exception:  # noqa: BLE001
                actual_value = 0.0

        value, display_text = _resolve_dimension_values(
            getattr(dim.dxf, "text", ""),
            _safe_float(actual_value),
        )
        z_min, z_max, z_ambiguous = _z_bounds(raw_defpoint, raw_defpoint2, raw_text_mid)
        elevation_band, z_band_ambiguous = _classify_elevation_band(z_min, z_max, layer_name=layer)

        return {
            "id": handle,
            "value": round(_safe_float(value), 6),
            "actual_value": round(_safe_float(actual_value), 6),
            "display_text": display_text,
            "layer": layer,
            "source": source,
            "defpoint": defpoint,
            "defpoint2": defpoint2,
            "text_position": text_pos,
            "z_min": z_min,
            "z_max": z_max,
            "z_range_label": "dimension_annotation",
            "elevation_band": elevation_band,
            "z_ambiguous": bool(z_ambiguous or z_band_ambiguous),
            "included_in_plan_extraction": True,
        }

    for query in _DIMENSION_QUERIES:
        for dim in doc.modelspace().query(query):
            item = make_item(dim, "model_space")
            if item:
                items.append(item)

    for query in _DIMENSION_QUERIES:
        for dim in layout.query(query):
            item = make_item(dim, "layout_space")
            if item:
                items.append(item)

    _collect_nested_dimensions(doc.modelspace(), "model_space", items, seen_handles,
                               visible_layers, model_ranges, model_range)

    return items


def _collect_nested_dimensions(
    space,
    source: str,
    items: List[Dict[str, Any]],
    seen_handles: Set[str],
    visible_layers: Set[str],
    model_ranges: Optional[Sequence[Dict[str, List[float]]]],
    model_range: Dict[str, List[float]],
) -> None:  # noqa: ANN001
    """Collect DIMENSION entities from nested INSERT blocks via virtual_entities."""
    for insert in space.query("INSERT"):
        layer = str(getattr(insert.dxf, "layer", "") or "")
        if visible_layers and layer and layer not in visible_layers:
            continue
        try:
            virtuals = list(insert.virtual_entities())
        except Exception:  # noqa: BLE001
            continue
        for entity in virtuals:
            etype = entity.dxftype()
            if etype not in ("DIMENSION", "ARC_DIMENSION"):
                continue
            handle = str(getattr(entity.dxf, "handle", "") or "")
            if handle in seen_handles:
                continue
            seen_handles.add(handle)

            elayer = str(getattr(entity.dxf, "layer", "") or "")
            if visible_layers and elayer and elayer not in visible_layers:
                continue

            text_pos = _point_xy(
                getattr(entity.dxf, "text_midpoint", None) or getattr(entity.dxf, "defpoint", None)
            )
            if not _point_in_any_range(text_pos, model_ranges, fallback_range=model_range, padding=200.0):
                continue

            actual_value = getattr(entity.dxf, "actual_measurement", None)
            if actual_value is None:
                try:
                    actual_value = entity.get_measurement()
                except Exception:  # noqa: BLE001
                    actual_value = 0.0

            value, display_text = _resolve_dimension_values(
                getattr(entity.dxf, "text", ""),
                _safe_float(actual_value),
            )
            raw_defpoint = getattr(entity.dxf, "defpoint", None)
            raw_defpoint2 = getattr(entity.dxf, "defpoint2", None)
            raw_text_mid = getattr(entity.dxf, "text_midpoint", None) or raw_defpoint
            z_min, z_max, z_ambiguous = _z_bounds(raw_defpoint, raw_defpoint2, raw_text_mid)
            elevation_band, z_band_ambiguous = _classify_elevation_band(z_min, z_max, layer_name=elayer)

            items.append({
                "id": handle,
                "value": round(_safe_float(value), 6),
                "actual_value": round(_safe_float(actual_value), 6),
                "display_text": display_text,
                "layer": elayer,
                "source": source,
                "defpoint": _point_xy(raw_defpoint),
                "defpoint2": _point_xy(raw_defpoint2),
                "text_position": text_pos,
                "z_min": z_min,
                "z_max": z_max,
                "z_range_label": "dimension_annotation",
                "elevation_band": elevation_band,
                "z_ambiguous": bool(z_ambiguous or z_band_ambiguous),
                "included_in_plan_extraction": True,
            })


def _extract_pseudo_texts(
    doc,
    layout,
    model_range: Dict[str, List[float]],
    visible_layers: Set[str],
    *,
    model_ranges: Optional[Sequence[Dict[str, List[float]]]] = None,
) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []

    def collect(space, source: str) -> None:  # noqa: ANN001
        for entity in space.query("TEXT MTEXT"):
            etype = entity.dxftype()
            layer = str(getattr(entity.dxf, "layer", "") or "")
            if visible_layers and layer and layer not in visible_layers:
                continue

            if etype == "TEXT":
                raw_text = str(getattr(entity.dxf, "text", "") or "")
                raw_pos = getattr(entity.dxf, "insert", None)
                pos = _point_xy(raw_pos)
            else:
                raw_text = str(getattr(entity, "text", "") or "")
                raw_pos = getattr(entity.dxf, "insert", None)
                pos = _point_xy(raw_pos)

            text = _normalize_plain_text(raw_text)
            if not _is_numeric_like_text(text):
                continue

            if source == "model_space" and not _point_in_any_range(
                pos,
                model_ranges,
                fallback_range=model_range,
                padding=200.0,
            ):
                continue

            numeric_value = _parse_numeric_text(text)
            font_name = str(getattr(entity.dxf, "style", "") or "")
            encoding_meta = _infer_encoding_meta(raw_text, font_name=font_name)
            z_min, z_max, z_ambiguous = _z_bounds(raw_pos)
            elevation_band, z_band_ambiguous = _classify_elevation_band(z_min, z_max, layer_name=layer)
            items.append(
                {
                    "id": str(getattr(entity.dxf, "handle", "") or ""),
                    "entity_type": etype,
                    "content": text,
                    "numeric_value": numeric_value if numeric_value is not None else 0.0,
                    "position": pos,
                    "layer": layer,
                    "source": source,
                    "encoding": encoding_meta,
                    "font_name": font_name or None,
                    "z_min": z_min,
                    "z_max": z_max,
                    "z_range_label": "annotation_text",
                    "elevation_band": elevation_band,
                    "z_ambiguous": bool(z_ambiguous or z_band_ambiguous),
                    "included_in_plan_extraction": True,
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


def _looks_like_index_number(value: str) -> bool:
    """分图号/详图编号可以是数字（01）、字母（A/B）或字母+数字（A01/01A）。"""
    text = str(value or "").strip().upper()
    if not text:
        return False
    # 纯字母（1-3个），如 A、B、AB
    if re.fullmatch(r"[A-Z]{1,3}", text):
        return True
    # 数字，或字母+数字组合，如 01、A01、01A
    return bool(re.fullmatch(r"[A-Z]?\d{1,3}[A-Z]?", text))


def _pick_generic_index_pair(attrs: Dict[str, str]) -> Tuple[str, str]:
    values = [str(value or "").strip() for value in attrs.values() if str(value or "").strip()]
    if len(values) < 2:
        return "", ""

    index_candidates = [value for value in values if _looks_like_index_number(value)]
    target_candidates = [value for value in values if _is_sheet_no_like(value)]

    if not index_candidates or not target_candidates:
        return "", ""

    for target_candidate in target_candidates:
        for index_candidate in index_candidates:
            if target_candidate != index_candidate:
                return index_candidate, target_candidate
    return "", ""


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
    model_ranges: Optional[Sequence[Dict[str, List[float]]]] = None,
    visible_layers: Set[str],
) -> List[Dict[str, Any]]:  # noqa: ANN001
    detail_titles: List[Dict[str, Any]] = []

    for insert in space.query("INSERT"):
        block_name = str(getattr(insert.dxf, "name", "") or "")
        layer = str(getattr(insert.dxf, "layer", "") or "")
        if source == "model_space" and visible_layers and layer and layer not in visible_layers:
            continue

        position = _point_xy(getattr(insert.dxf, "insert", None))
        if source == "model_space" and not _point_in_any_range(
            position,
            model_ranges,
            fallback_range=model_range,
            padding=200.0,
        ):
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
    *,
    model_ranges: Optional[Sequence[Dict[str, List[float]]]] = None,
    capture_inserts: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], str, str]:  # noqa: ANN001
    indexes: List[Dict[str, Any]] = []
    title_blocks: List[Dict[str, Any]] = []
    detail_titles: List[Dict[str, Any]] = []
    first_sheet_no = ""
    first_sheet_name = ""

    def process_insert(insert, *, source: str) -> None:  # noqa: ANN001
        nonlocal first_sheet_name, first_sheet_no
        block_name = str(getattr(insert.dxf, "name", "") or "")
        upper_name = block_name.upper()
        layer = str(getattr(insert.dxf, "layer", "") or "")
        if source == "model_space" and visible_layers and layer and layer not in visible_layers:
            return
        position = _point_xy(getattr(insert.dxf, "insert", None))
        if source == "model_space" and not _point_in_any_range(
            position,
            model_ranges,
            fallback_range=model_range,
            padding=200.0,
        ):
            return

        attrs: Dict[str, str] = {}
        for attrib in getattr(insert, "attribs", []):
            tag = str(getattr(attrib.dxf, "tag", "") or "").upper().strip()
            text = str(getattr(attrib.dxf, "text", "") or "").strip()
            if tag:
                attrs[tag] = text

        insert_snapshot = _build_insert_snapshot(
            insert,
            block_name=block_name,
            layer=layer,
            attrs=attrs,
            position=position,
            source=source,
        )
        if capture_inserts is not None:
            capture_inserts.append(insert_snapshot)

        index_no_keys = (
            "_ACM-CALLOUTNUMBER", "_ACM-SECTIONLABEL", "REF#",
            "INDEX_NO", "INDEX", "NO", "NUM", "编号", "序号", "SN", "DN",
        )
        target_sheet_keys = (
            "_ACM-SHEETNUMBER", "SHT", "SHEET", "TARGET",
            "图号", "DRAWINGNO", "DRAWNO", "SHEETNO",
        )
        title_no_keys = ("图号", "DRAWNO", "DRAWINGNO", "SHEETNO")
        title_name_keys = ("图名", "DRAWNAME", "SHEETNAME", "_ACM-TITLEMARK")

        def pick_attr(keys) -> str:  # noqa: ANN001
            for key in keys:
                if attrs.get(key):
                    return attrs[key]
            return ""

        detail_title_candidate = _extract_detail_title_from_insert(
            insert, attrs,
            block_name=block_name, layer=layer, position=position, source=source,
        )

        idx_no_candidate = pick_attr(index_no_keys)
        target_candidate = pick_attr(target_sheet_keys)
        if not detail_title_candidate and not (idx_no_candidate and target_candidate):
            generic_idx_no, generic_target = _pick_generic_index_pair(attrs)
            idx_no_candidate = idx_no_candidate or generic_idx_no
            target_candidate = target_candidate or generic_target

        # 检测本图索引（下方为短横线）：索引和被引详图都在当前图纸内，不涉及跨图跳转
        # 常见写法："-"、"—"、"--"、"_" 等
        _SAME_SHEET_MARKERS = {"-", "—", "–", "--", "——", "—", "＿", "_", "一"}
        is_same_sheet_index = target_candidate.strip() in _SAME_SHEET_MARKERS
        if is_same_sheet_index:
            target_candidate = ""  # 本图索引：不需要跨图验证，清除目标图号

        # 过滤假阳性：target_sheet 必须是真正的图号格式（含字母+数字），
        # 且不能与 index_no 相同（相同时几乎必定是分图号/平面图标识，而非跨图索引）
        if target_candidate and not _is_sheet_no_like(target_candidate):
            target_candidate = ""
        if (
            target_candidate
            and target_candidate.strip().upper() == idx_no_candidate.strip().upper()
        ):
            target_candidate = ""

        has_index_pair = bool(idx_no_candidate and target_candidate)
        has_index_tag = any(any(keyword in key for keyword in INDEX_KEYWORDS) for key in attrs)
        has_callout_tag = any(key in attrs for key in ("_ACM-CALLOUTNUMBER", "_ACM-SECTIONLABEL", "REF#"))
        has_sheet_ref_tag = any(key in attrs for key in ("_ACM-SHEETNUMBER", "SHT", "SHEET", "SHEETNO"))

        is_revision_mark = (
            "MODIFY" in upper_name
            or "修改" in upper_name
            or "REVISION" in upper_name
            or "REV" == upper_name
            or any("修改" in str(v) for v in attrs.values())
        )

        is_index = (
            not is_revision_mark
            and (
                any(keyword in upper_name for keyword in INDEX_KEYWORDS)
                or has_index_tag
                or has_index_pair
                or (has_callout_tag and has_sheet_ref_tag)
            )
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
                    "same_sheet": is_same_sheet_index,  # 本图索引标记，下方为短横线
                    "source": source,
                    "position": visual_anchor,
                    "insert_position": position,
                    "anchor_source": anchor_source,
                    "symbol_bbox": symbol_bbox,
                    "layer": layer,
                    "attrs": _attr_list(attrs),
                    "z_min": insert_snapshot.get("z_min"),
                    "z_max": insert_snapshot.get("z_max"),
                    "z_range_label": insert_snapshot.get("z_range_label"),
                    "elevation_band": insert_snapshot.get("elevation_band"),
                    "z_ambiguous": insert_snapshot.get("z_ambiguous"),
                    "is_dynamic_block": insert_snapshot.get("is_dynamic_block"),
                    "effective_geometry": insert_snapshot.get("effective_geometry"),
                }
            )

        if is_title and source == "layout_space":
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
                    "source": source,
                    "layer": layer,
                    "attrs": _attr_list(attrs),
                    "z_min": insert_snapshot.get("z_min"),
                    "z_max": insert_snapshot.get("z_max"),
                    "elevation_band": insert_snapshot.get("elevation_band"),
                }
            )

        if detail_title_candidate:
            detail_titles.append(detail_title_candidate)

    for insert in layout.query("INSERT"):
        process_insert(insert, source="layout_space")

    for insert in doc.modelspace().query("INSERT"):
        process_insert(insert, source="model_space")

    return indexes, title_blocks, detail_titles, first_sheet_no, first_sheet_name
