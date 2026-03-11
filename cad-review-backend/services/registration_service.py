"""Registration helpers for mapping layout anchors to PDF page anchors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image

from models import Drawing, DrawingLayoutRegistration, JsonData
from services.audit.common import build_anchor, safe_float
from services.layout_json_service import load_enriched_layout_json


def _parse_json(text: Optional[str]) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _normalize_range(value: Any) -> Optional[Dict[str, list[float]]]:
    if not isinstance(value, dict):
        return None
    mn = value.get("min")
    mx = value.get("max")
    if not isinstance(mn, (list, tuple)) or not isinstance(mx, (list, tuple)) or len(mn) < 2 or len(mx) < 2:
        return None
    try:
        x_min = float(mn[0])
        y_min = float(mn[1])
        x_max = float(mx[0])
        y_max = float(mx[1])
    except (TypeError, ValueError):
        return None
    if x_max <= x_min or y_max <= y_min:
        return None
    return {"min": [x_min, y_min], "max": [x_max, y_max]}


def _get_png_size(png_path: Optional[str]) -> Optional[Dict[str, int]]:
    if not png_path:
        return None
    path = Path(png_path).expanduser()
    if not path.exists():
        return None
    try:
        with Image.open(path) as image:
            return {"width": int(image.width), "height": int(image.height)}
    except Exception:
        return None


def _resolve_json_for_drawing(drawing: Drawing, db) -> tuple[Optional[JsonData], Optional[Dict[str, Any]]]:
    if not drawing.sheet_no:
        return None, None
    rows = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == drawing.project_id,
            JsonData.sheet_no == drawing.sheet_no,
            JsonData.is_latest == 1,
        )
        .order_by(JsonData.created_at.desc())
        .all()
    )
    exact_rows = [row for row in rows if int(row.data_version or 0) == int(drawing.data_version or 0)]
    candidate_rows = exact_rows or sorted(rows, key=lambda row: int(row.data_version or 0), reverse=True)
    for row in candidate_rows:
        if not row.json_path:
            continue
        payload = load_enriched_layout_json(row.json_path)
        if payload:
            return row, payload
    return None, None


def _compute_registration_quality(
    *,
    drawing: Drawing,
    json_row: Optional[JsonData],
    layout_page_range: Dict[str, list[float]],
    pdf_page_size: Dict[str, int],
) -> tuple[str, float]:
    method = "layout_page_direct"
    confidence = 1.0

    drawing_version = int(drawing.data_version or 0)
    json_version = int(json_row.data_version or 0) if json_row is not None else 0
    if json_row is not None and drawing_version and json_version and drawing_version != json_version:
        method = "layout_page_version_fallback"
        confidence = min(confidence, 0.55)

    layout_width = layout_page_range["max"][0] - layout_page_range["min"][0]
    layout_height = layout_page_range["max"][1] - layout_page_range["min"][1]
    pdf_width = float(pdf_page_size["width"])
    pdf_height = float(pdf_page_size["height"])
    if layout_width > 0 and layout_height > 0 and pdf_width > 0 and pdf_height > 0:
        layout_ratio = layout_width / layout_height
        pdf_ratio = pdf_width / pdf_height
        ratio_delta = abs(layout_ratio - pdf_ratio) / max(layout_ratio, pdf_ratio, 1e-6)
        if ratio_delta > 0.08 and 0.35 < confidence:
            method = "layout_page_ratio_mismatch"
            confidence = 0.35
        elif ratio_delta > 0.03 and 0.75 < confidence:
            method = "layout_page_ratio_adjusted"
            confidence = 0.75

    return method, round(confidence, 3)


def ensure_drawing_registration(drawing: Optional[Drawing], db) -> Optional[DrawingLayoutRegistration]:
    if drawing is None:
        return None

    existing = (
        db.query(DrawingLayoutRegistration)
        .filter(DrawingLayoutRegistration.drawing_id == drawing.id)
        .order_by(DrawingLayoutRegistration.updated_at.desc())
        .first()
    )

    json_row, payload = _resolve_json_for_drawing(drawing, db)
    if not payload:
        return existing

    layout_page_range = _normalize_range(payload.get("layout_page_range"))
    pdf_page_size = _get_png_size(drawing.png_path)
    layout_name = str(payload.get("layout_name") or "").strip()
    if layout_page_range is None or pdf_page_size is None or not layout_name:
        return existing

    registration_method, registration_confidence = _compute_registration_quality(
        drawing=drawing,
        json_row=json_row,
        layout_page_range=layout_page_range,
        pdf_page_size=pdf_page_size,
    )
    transform_payload = {
        "type": "direct_layout_page",
        "layout_page_range": layout_page_range,
        "pdf_page_size": pdf_page_size,
        "json_data_version": int(json_row.data_version or 0) if json_row is not None else None,
    }

    if existing:
        existing.layout_name = layout_name
        existing.pdf_page_index = drawing.page_index
        existing.layout_page_range_json = json.dumps(layout_page_range, ensure_ascii=False)
        existing.pdf_page_size_json = json.dumps(pdf_page_size, ensure_ascii=False)
        existing.transform_json = json.dumps(transform_payload, ensure_ascii=False)
        existing.registration_method = registration_method
        existing.registration_confidence = registration_confidence
        return existing

    record = DrawingLayoutRegistration(
        project_id=drawing.project_id,
        drawing_id=drawing.id,
        drawing_data_version=drawing.data_version,
        sheet_no=drawing.sheet_no,
        layout_name=layout_name,
        pdf_page_index=drawing.page_index,
        layout_page_range_json=json.dumps(layout_page_range, ensure_ascii=False),
        pdf_page_size_json=json.dumps(pdf_page_size, ensure_ascii=False),
        transform_json=json.dumps(transform_payload, ensure_ascii=False),
        registration_method=registration_method,
        registration_confidence=registration_confidence,
    )
    db.add(record)
    db.flush()
    return record


def build_pdf_anchor(
    *,
    layout_anchor: Optional[Dict[str, Any]],
    registration: Optional[DrawingLayoutRegistration],
) -> Optional[Dict[str, Any]]:
    if not isinstance(layout_anchor, dict):
        return None

    if registration is None:
        anchor = build_anchor(
            role=str(layout_anchor.get("role") or "").strip() or "source",
            sheet_no=str(layout_anchor.get("sheet_no") or "").strip() or None,
            grid=str(layout_anchor.get("grid") or "").strip() or None,
            global_pct=layout_anchor.get("global_pct") if isinstance(layout_anchor.get("global_pct"), dict) else None,
            confidence=safe_float(layout_anchor.get("confidence")),
            origin=str(layout_anchor.get("origin") or "index"),
        )
        if anchor is None and isinstance(layout_anchor.get("global_pct"), dict):
            anchor = dict(layout_anchor)
        if anchor is not None:
            anchor["anchor_type"] = "pdf"
            if isinstance(layout_anchor.get("highlight_region"), dict):
                anchor["highlight_region"] = layout_anchor.get("highlight_region")
            return anchor

    point = layout_anchor.get("layout_point")
    layout_page_range = _normalize_range(_parse_json(registration.layout_page_range_json))
    if isinstance(point, dict) and layout_page_range is not None:
        x = safe_float(point.get("x"))
        y = safe_float(point.get("y"))
        if x is not None and y is not None:
            x_min, y_min = layout_page_range["min"]
            x_max, y_max = layout_page_range["max"]
            pct_x = round(max(0.0, min(100.0, ((x - x_min) / (x_max - x_min)) * 100.0)), 1)
            pct_y = round(max(0.0, min(100.0, (1.0 - ((y - y_min) / (y_max - y_min))) * 100.0)), 1)
            anchor = build_anchor(
                role=str(layout_anchor.get("role") or "").strip() or "source",
                sheet_no=str(layout_anchor.get("sheet_no") or "").strip() or None,
                grid=str(layout_anchor.get("grid") or "").strip() or None,
                global_pct={"x": pct_x, "y": pct_y},
                confidence=min(1.0, max(0.0, (safe_float(layout_anchor.get("confidence")) or 0.0) * (registration.registration_confidence or 1.0))),
                origin=str(layout_anchor.get("origin") or "index"),
            )
            if anchor is not None:
                anchor["anchor_type"] = "pdf"
                anchor["registration_method"] = registration.registration_method
                return anchor

    anchor = build_anchor(
        role=str(layout_anchor.get("role") or "").strip() or "source",
        sheet_no=str(layout_anchor.get("sheet_no") or "").strip() or None,
        grid=str(layout_anchor.get("grid") or "").strip() or None,
        global_pct=layout_anchor.get("global_pct") if isinstance(layout_anchor.get("global_pct"), dict) else None,
        confidence=min(1.0, max(0.0, (safe_float(layout_anchor.get("confidence")) or 0.0) * (registration.registration_confidence or 1.0))),
        origin=str(layout_anchor.get("origin") or "index"),
    )
    if anchor is None and isinstance(layout_anchor.get("global_pct"), dict):
        anchor = dict(layout_anchor)
    if anchor is not None:
        anchor["anchor_type"] = "pdf"
        anchor["registration_method"] = registration.registration_method
        if isinstance(layout_anchor.get("highlight_region"), dict):
            anchor["highlight_region"] = layout_anchor.get("highlight_region")
    return anchor


def resolve_anchor_status(
    *,
    layout_anchor: Optional[Dict[str, Any]],
    pdf_anchor: Optional[Dict[str, Any]],
    registration: Optional[DrawingLayoutRegistration],
) -> str:
    if isinstance(pdf_anchor, dict):
        if registration is None:
            return "layout_fallback"
        image_evidence = pdf_anchor.get("image_evidence")
        if (
            isinstance(image_evidence, dict)
            and safe_float(image_evidence.get("dark_ratio")) is not None
            and safe_float(image_evidence.get("dark_ratio")) <= 0.0005
            and (registration.registration_confidence or 0.0) >= 0.9
        ):
            return "pdf_visual_mismatch"
        confidence = safe_float(pdf_anchor.get("confidence"))
        if confidence is not None and confidence < 0.6:
            return "pdf_low_confidence"
        return "pdf_ready"
    if isinstance(layout_anchor, dict):
        return "layout_only"
    return "missing"


def apply_image_evidence(
    *,
    pdf_anchor: Optional[Dict[str, Any]],
    drawing: Optional[Drawing],
    radius: int = 120,
) -> Optional[Dict[str, Any]]:
    if not isinstance(pdf_anchor, dict) or drawing is None or not drawing.png_path:
        return pdf_anchor
    point = pdf_anchor.get("global_pct")
    if not isinstance(point, dict):
        return pdf_anchor

    pct_x = safe_float(point.get("x"))
    pct_y = safe_float(point.get("y"))
    if pct_x is None or pct_y is None:
        return pdf_anchor

    path = Path(drawing.png_path).expanduser()
    if not path.exists():
        return pdf_anchor

    try:
        with Image.open(path) as image:
            source = image.convert("RGBA")
            width, height = source.size
            center_x = int(width * (pct_x / 100.0))
            center_y = int(height * (pct_y / 100.0))
            left = max(0, center_x - radius)
            top = max(0, center_y - radius)
            right = min(width, center_x + radius)
            bottom = min(height, center_y + radius)
            crop = source.crop((left, top, right, bottom))
            data = crop.tobytes()
    except Exception:
        return pdf_anchor

    alpha_threshold = 8
    white_threshold = 246
    total = 0
    dark = 0
    for i in range(0, len(data), 4):
        r, g, b, a = data[i : i + 4]
        if a < alpha_threshold:
            continue
        total += 1
        if not (r >= white_threshold and g >= white_threshold and b >= white_threshold):
            dark += 1

    dark_ratio = dark / max(1, total)
    if dark_ratio >= 0.0025:
        return pdf_anchor

    next_anchor = dict(pdf_anchor)
    next_anchor["confidence"] = min(safe_float(pdf_anchor.get("confidence")) or 1.0, 0.35)
    next_anchor["image_evidence"] = {
        "dark_ratio": round(dark_ratio, 4),
        "sample_radius": radius,
    }
    return next_anchor
