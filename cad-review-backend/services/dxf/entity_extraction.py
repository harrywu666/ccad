"""标注、伪文本、索引、详图标题提取。"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from services.dxf.geo_utils import _point_in_any_range, _point_xy, _safe_float
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

        defpoint = _point_xy(getattr(dim.dxf, "defpoint", None))
        defpoint2 = _point_xy(getattr(dim.dxf, "defpoint2", None))
        text_pos = _point_xy(
            getattr(dim.dxf, "text_midpoint", None) or getattr(dim.dxf, "defpoint", None)
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

            items.append({
                "id": handle,
                "value": round(_safe_float(value), 6),
                "actual_value": round(_safe_float(actual_value), 6),
                "display_text": display_text,
                "layer": elayer,
                "source": source,
                "defpoint": _point_xy(getattr(entity.dxf, "defpoint", None)),
                "defpoint2": _point_xy(getattr(entity.dxf, "defpoint2", None)),
                "text_position": text_pos,
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
                pos = _point_xy(getattr(entity.dxf, "insert", None))
            else:
                raw_text = str(getattr(entity, "text", "") or "")
                pos = _point_xy(getattr(entity.dxf, "insert", None))

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
    model_ranges: Optional[Sequence[Dict[str, List[float]]]] = None,
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
                }
            )

        if detail_title_candidate:
            detail_titles.append(detail_title_candidate)

    for insert in layout.query("INSERT"):
        process_insert(insert, source="layout_space")

    for insert in doc.modelspace().query("INSERT"):
        process_insert(insert, source="model_space")

    return indexes, title_blocks, detail_titles, first_sheet_no, first_sheet_name
