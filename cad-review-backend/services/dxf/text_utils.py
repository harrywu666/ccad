"""文本/命名工具 + 文本实体收集。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set

from domain.text_cleaning import strip_mtext_formatting
from services.dxf.geo_utils import _point_in_any_range, _point_xy

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
        r"(?<![A-Za-z])[A-Z]{1,3}\d{0,3}[.\-_]\d{1,3}[a-zA-Z]?(?![A-Za-z])",
        r"(?<![A-Za-z])[A-Z]\d{1,4}[a-zA-Z]?(?![A-Za-z])",
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


def _is_standalone_sheet_no_text(text: str, sheet_no: str) -> bool:
    plain = _normalize_plain_text(text).upper().replace(" ", "")
    candidate = _normalize_plain_text(sheet_no).upper().replace(" ", "")
    if not plain or not candidate:
        return False
    if plain == candidate:
        return True
    allowed_prefixes = {
        "图号",
        "图纸编号",
        "SHEETNO",
        "SHEET",
        "NO",
        "NO.",
    }
    for prefix in allowed_prefixes:
        if plain == f"{prefix}{candidate}":
            return True
    return False


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


def _display_scale(scale: float) -> str:
    if scale <= 0:
        return ""
    ratio = round(1.0 / scale)
    if ratio <= 0:
        return ""
    return f"1:{ratio}"


def _extract_layout_page_range(layout) -> Dict[str, List[float]]:  # noqa: ANN001
    from services.dxf.geo_utils import _safe_float

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


def _collect_text_entities_from_space(
    space,
    *,
    source: str,
    model_range: Optional[Dict[str, List[float]]] = None,
    model_ranges: Optional[Sequence[Dict[str, List[float]]]] = None,
    visible_layers: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:  # noqa: ANN001
    texts: List[Dict[str, Any]] = []

    def _accept_text(entity, etype: str) -> None:  # noqa: ANN001
        layer = str(getattr(entity.dxf, "layer", "") or "")
        if source == "model_space" and visible_layers and layer and layer not in visible_layers:
            return
        if etype == "TEXT":
            text = str(getattr(entity.dxf, "text", "") or "").strip()
        else:
            text = strip_mtext_formatting(str(getattr(entity, "text", "") or ""))
        position = _point_xy(getattr(entity.dxf, "insert", None))
        if source == "model_space" and not _point_in_any_range(
            position, model_ranges, fallback_range=model_range, padding=200.0,
        ):
            return
        if text:
            texts.append({"text": text, "position": position, "source": source, "layer": layer})

    for entity in space.query("TEXT"):
        _accept_text(entity, "TEXT")

    for entity in space.query("MTEXT"):
        _accept_text(entity, "MTEXT")

    if source == "model_space":
        _collect_nested_texts(space, texts, source, model_range, model_ranges, visible_layers)

    return texts


def _collect_nested_texts(
    space,
    texts: List[Dict[str, Any]],
    source: str,
    model_range: Optional[Dict[str, List[float]]],
    model_ranges: Optional[Sequence[Dict[str, List[float]]]],
    visible_layers: Optional[Set[str]],
) -> None:  # noqa: ANN001
    """Collect TEXT/MTEXT from nested INSERT blocks via virtual_entities."""
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
            if etype not in ("TEXT", "MTEXT"):
                continue
            elayer = str(getattr(entity.dxf, "layer", "") or "")
            if visible_layers and elayer and elayer not in visible_layers:
                continue
            if etype == "TEXT":
                text = str(getattr(entity.dxf, "text", "") or "").strip()
            else:
                text = strip_mtext_formatting(str(getattr(entity, "text", "") or ""))
            position = _point_xy(getattr(entity.dxf, "insert", None))
            if not _point_in_any_range(position, model_ranges, fallback_range=model_range, padding=200.0):
                continue
            if text:
                texts.append({"text": text, "position": position, "source": source, "layer": elayer})


def _collect_text_entities(layout) -> List[Dict[str, Any]]:  # noqa: ANN001
    return _collect_text_entities_from_space(layout, source="layout_space")
