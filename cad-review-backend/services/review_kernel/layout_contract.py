"""布局 JSON 合同补齐。

用于把历史版本（字段不全）的布局 JSON 自动补齐到 review_kernel 当前可消费的最小结构。
该补齐只做结构兜底，不会伪造不存在的 CAD 语义证据。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _build_layer_state_snapshot(layout_name: str, layers: List[Dict[str, Any]], viewports: List[Dict[str, Any]]) -> Dict[str, Any]:
    layer_visibility: List[Dict[str, Any]] = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("name") or layer.get("layer_name") or "").strip()
        if not name:
            continue
        visible = layer.get("visible")
        if visible is None:
            is_on = bool(layer.get("on", True))
            is_frozen = bool(layer.get("frozen", False))
            visible = is_on and (not is_frozen)
        layer_visibility.append({"layer_name": name, "visible": bool(visible)})

    overrides: List[Dict[str, Any]] = []
    for viewport in viewports:
        if not isinstance(viewport, dict):
            continue
        viewport_id = str(viewport.get("id") or viewport.get("viewport_id") or "").strip()
        for item in _as_list(viewport.get("layer_overrides")):
            if not isinstance(item, dict):
                continue
            layer_name = str(item.get("layer_name") or "").strip()
            if not layer_name:
                continue
            overrides.append(
                {
                    "viewport_id": viewport_id or None,
                    "layer_name": layer_name,
                    "visible": bool(item.get("visible")),
                    "override_type": str(item.get("override_type") or "vp_freeze"),
                }
            )

    return {
        "layer_state_id": f"LST-{layout_name or 'layout'}",
        "owner_layout_name": layout_name or "layout",
        "name": f"{layout_name or 'layout'}_STATE",
        "layer_visibility": layer_visibility,
        "viewport_overrides": overrides,
        "source": "viewport_overrides" if overrides else "layout_embedded_state",
        "confidence": 0.95 if layer_visibility else 0.6,
    }


def _build_text_encoding_evidence(pseudo_texts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    for item in pseudo_texts:
        if not isinstance(item, dict):
            continue
        encoding = _as_dict(item.get("encoding"))
        if not encoding:
            continue
        evidence.append(
            {
                "source_entity_id": str(item.get("id") or ""),
                "encoding_detected": encoding.get("encoding_detected"),
                "encoding_confidence": encoding.get("encoding_confidence"),
                "font_name": encoding.get("font_name"),
                "font_substitution": encoding.get("font_substitution"),
                "font_substitution_reason": encoding.get("font_substitution_reason"),
                "ocr_triggered": bool(encoding.get("ocr_triggered")),
                "ocr_fallback": encoding.get("ocr_fallback"),
            }
        )
    return evidence


def _build_z_range_summary(groups: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    z_min = None
    z_max = None
    ambiguous_count = 0
    sample_count = 0
    for group in groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            low = item.get("z_min")
            high = item.get("z_max")
            if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                sample_count += 1
                z_min = low if z_min is None else min(z_min, low)
                z_max = high if z_max is None else max(z_max, high)
            if bool(item.get("z_ambiguous")):
                ambiguous_count += 1
    return {
        "z_min": round(float(z_min), 3) if z_min is not None else 0.0,
        "z_max": round(float(z_max), 3) if z_max is not None else 0.0,
        "ambiguous_count": int(ambiguous_count),
        "sample_count": int(sample_count),
    }


def ensure_layout_json_contract(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, List[str]]:
    """补齐布局 JSON 合同字段。

    Returns:
        (payload, changed, changed_fields)
    """
    changed_fields: List[str] = []
    if not isinstance(payload, dict):
        return payload, False, changed_fields

    layout_name = str(payload.get("layout_name") or "").strip()
    sheet_no = str(payload.get("sheet_no") or "").strip()
    sheet_name = str(payload.get("sheet_name") or "").strip()
    source_dwg = str(payload.get("source_dwg") or "").strip()

    if "schema_version" not in payload:
        payload["schema_version"] = "1.2.0"
        changed_fields.append("schema_version")
    if "schema_name" not in payload:
        payload["schema_name"] = "dwg_layout_semantic_payload"
        changed_fields.append("schema_name")

    list_fields = [
        "viewports",
        "dimensions",
        "pseudo_texts",
        "indexes",
        "title_blocks",
        "detail_titles",
        "materials",
        "material_table",
        "layers",
        "layout_frames",
        "layout_fragments",
        "insert_entities",
    ]
    for field in list_fields:
        if not isinstance(payload.get(field), list):
            payload[field] = _as_list(payload.get(field))
            changed_fields.append(field)

    if "is_multi_sheet_layout" not in payload:
        payload["is_multi_sheet_layout"] = len(_as_list(payload.get("layout_fragments"))) > 1
        changed_fields.append("is_multi_sheet_layout")

    if "scale" not in payload:
        payload["scale"] = ""
        changed_fields.append("scale")

    model_range = _as_dict(payload.get("model_range"))
    if not model_range:
        payload["model_range"] = {"min": [0.0, 0.0], "max": [0.0, 0.0]}
        changed_fields.append("model_range")

    layout_page_range = _as_dict(payload.get("layout_page_range"))
    if not layout_page_range:
        payload["layout_page_range"] = {"min": [0.0, 0.0], "max": [0.0, 0.0]}
        changed_fields.append("layout_page_range")

    if not isinstance(payload.get("layer_state_snapshot"), dict):
        payload["layer_state_snapshot"] = _build_layer_state_snapshot(
            layout_name=layout_name,
            layers=_as_list(payload.get("layers")),
            viewports=_as_list(payload.get("viewports")),
        )
        changed_fields.append("layer_state_snapshot")

    if not isinstance(payload.get("text_encoding_evidence"), list):
        payload["text_encoding_evidence"] = _build_text_encoding_evidence(_as_list(payload.get("pseudo_texts")))
        changed_fields.append("text_encoding_evidence")

    if not isinstance(payload.get("z_range_summary"), dict):
        payload["z_range_summary"] = _build_z_range_summary(
            [
                _as_list(payload.get("dimensions")),
                _as_list(payload.get("pseudo_texts")),
                _as_list(payload.get("indexes")),
                _as_list(payload.get("title_blocks")),
                _as_list(payload.get("insert_entities")),
                _as_list(payload.get("materials")),
            ]
        )
        changed_fields.append("z_range_summary")
    else:
        z_summary = _as_dict(payload.get("z_range_summary"))
        z_summary.setdefault("z_min", _safe_float(z_summary.get("z_min")))
        z_summary.setdefault("z_max", _safe_float(z_summary.get("z_max")))
        z_summary.setdefault("ambiguous_count", int(z_summary.get("ambiguous_count") or 0))
        z_summary.setdefault("sample_count", int(z_summary.get("sample_count") or 0))
        payload["z_range_summary"] = z_summary

    if not isinstance(payload.get("drawing_register_entry"), dict):
        payload["drawing_register_entry"] = {
            "sheet_number": sheet_no,
            "title": sheet_name or layout_name,
            "layout_name": layout_name,
            "sheet_type": "unknown",
            "document_id": source_dwg or None,
        }
        changed_fields.append("drawing_register_entry")
    else:
        entry = _as_dict(payload.get("drawing_register_entry"))
        entry.setdefault("sheet_number", sheet_no)
        entry.setdefault("title", sheet_name or layout_name)
        entry.setdefault("layout_name", layout_name)
        entry.setdefault("sheet_type", "unknown")
        entry.setdefault("document_id", source_dwg or None)
        payload["drawing_register_entry"] = entry

    return payload, bool(changed_fields), changed_fields


__all__ = ["ensure_layout_json_contract"]
