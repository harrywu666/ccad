"""材料表提取。"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Set

from domain.text_cleaning import strip_mtext_formatting
from services.dxf.geo_utils import _distance, _point_in_any_range, _point_xy, _safe_float
from services.dxf.text_utils import (
    MATERIAL_LAYER_KEYWORDS,
    _collect_text_entities,
    _collect_text_entities_from_space,
)

logger = logging.getLogger(__name__)


def _mleader_position(ml) -> List[float]:  # noqa: ANN001
    """Extract arrow/leader position from MULTILEADER context."""
    ctx = getattr(ml, "context", None)
    if ctx is not None:
        for leader_data in getattr(ctx, "leaders", []) or []:
            for line in getattr(leader_data, "lines", []) or []:
                verts = list(getattr(line, "vertices", []) or [])
                if verts:
                    return _point_xy(verts[0])
        mtext_data = getattr(ctx, "mtext", None)
        if mtext_data is not None:
            insert = getattr(mtext_data, "insert", None)
            if insert is not None:
                return _point_xy(insert)
    return _point_xy(
        getattr(ml.dxf, "insert", None)
        or getattr(ml.dxf, "base_point", None)
        or getattr(ml.dxf, "arrow_head", None)
    )


def _mleader_content(ml, doc=None) -> str:  # noqa: ANN001
    """Extract text content from MULTILEADER (mtext-type and block-type)."""
    if hasattr(ml, "get_mtext_content"):
        try:
            text = ml.get_mtext_content()
            if text:
                return strip_mtext_formatting(str(text))
        except Exception:  # noqa: BLE001
            pass

    text = str(getattr(ml.dxf, "text", "") or "")
    if text.strip():
        return strip_mtext_formatting(text)

    ctx = getattr(ml, "context", None)
    if ctx is None:
        return ""

    block_data = getattr(ctx, "block", None)
    if block_data is None:
        return ""

    if hasattr(block_data, "block_attribs") and block_data.block_attribs:
        parts = [str(v).strip() for v in block_data.block_attribs.values() if str(v).strip()]
        if parts:
            return strip_mtext_formatting(" ".join(parts))

    if doc is None:
        return ""
    brh = getattr(block_data, "block_record_handle", None)
    if not brh:
        return ""
    try:
        br = doc.entitydb[brh]
        block_name = str(getattr(br.dxf, "name", "") or "")
        if not block_name:
            return ""
        block_def = doc.blocks[block_name]
        parts = []
        for entity in block_def:
            if entity.dxftype() == "ATTDEF":
                default_text = str(getattr(entity.dxf, "text", "") or "").strip()
                if default_text:
                    parts.append(default_text)
        if parts:
            return strip_mtext_formatting(" ".join(parts))
    except Exception:  # noqa: BLE001
        pass

    return ""


def _extract_materials_from_space(
    space,
    *,
    source: str,
    doc: Optional[Any] = None,
    model_range: Optional[Dict[str, List[float]]] = None,
    model_ranges: Optional[Sequence[Dict[str, List[float]]]] = None,
    visible_layers: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    text_entities = _collect_text_entities_from_space(
        space,
        source=source,
        model_range=model_range,
        model_ranges=model_ranges,
        visible_layers=visible_layers,
    )

    try:
        ml_entities = list(space.query("MLEADER"))
    except Exception:  # noqa: BLE001
        ml_entities = []

    try:
        ml_entities += list(space.query("MULTILEADER"))
    except Exception:  # noqa: BLE001
        pass

    for ml in ml_entities:
        layer = str(getattr(ml.dxf, "layer", "") or "")
        if source == "model_space" and visible_layers and layer and layer not in visible_layers:
            continue

        content = _mleader_content(ml, doc=doc)
        arrow = _mleader_position(ml)

        if source == "model_space" and not _point_in_any_range(
            arrow,
            model_ranges,
            fallback_range=model_range,
            padding=200.0,
        ):
            continue

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
                    "source": source,
                    "layer": layer,
                }
            )

    for leader in space.query("LEADER"):
        layer = str(getattr(leader.dxf, "layer", "") or "")
        if source == "model_space" and visible_layers and layer and layer not in visible_layers:
            continue
        vertices = []
        raw_vertices = getattr(leader, "vertices", None)
        if raw_vertices is not None:
            try:
                if callable(raw_vertices):
                    raw_vertices = raw_vertices()  # pyright: ignore[reportCallIssue]
                vertices = [_point_xy(point) for point in raw_vertices]
            except Exception:  # noqa: BLE001
                vertices = []

        arrow = vertices[0] if vertices else _point_xy(getattr(leader.dxf, "insert", None))
        text_anchor_candidates = vertices if vertices else [arrow]
        if source == "model_space" and not _point_in_any_range(
            arrow,
            model_ranges,
            fallback_range=model_range,
            padding=200.0,
        ):
            continue

        nearest_text = ""
        nearest_dist = 1e9
        for text_obj in text_entities:
            dist = min(_distance(point, text_obj["position"]) for point in text_anchor_candidates)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_text = text_obj["text"]

        if nearest_dist > 300.0:
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
                    "source": source,
                    "layer": layer,
                }
            )

    return items


def _extract_materials(
    doc,
    layout,
    model_range: Dict[str, List[float]],
    visible_layers: Set[str],
    *,
    model_ranges: Optional[Sequence[Dict[str, List[float]]]] = None,
) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    items.extend(
        _extract_materials_from_space(
            doc.modelspace(),
            source="model_space",
            doc=doc,
            model_range=model_range,
            model_ranges=model_ranges,
            visible_layers=visible_layers,
        )
    )
    items.extend(
        _extract_materials_from_space(
            layout,
            source="layout_space",
            doc=doc,
            model_range=model_range,
            model_ranges=model_ranges,
            visible_layers=visible_layers,
        )
    )
    return items


def _pair_material_rows_from_text(layout) -> List[Dict[str, str]]:  # noqa: ANN001
    texts = _collect_text_entities(layout)
    if not texts:
        return []

    texts_sorted = sorted(texts, key=lambda item: (-item["position"][1], item["position"][0]))

    if len(texts_sorted) >= 4:
        y_deltas = sorted(
            abs(texts_sorted[i]["position"][1] - texts_sorted[i + 1]["position"][1])
            for i in range(len(texts_sorted) - 1)
            if abs(texts_sorted[i]["position"][1] - texts_sorted[i + 1]["position"][1]) > 0.5
        )
        row_tol = y_deltas[len(y_deltas) // 4] * 0.6 if y_deltas else 30.0
        row_tol = max(5.0, min(row_tol, 80.0))
    else:
        row_tol = 30.0

    rows: List[List[Dict[str, Any]]] = []
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
