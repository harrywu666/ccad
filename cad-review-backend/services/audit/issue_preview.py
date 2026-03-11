"""Issue preview persistence and lookup helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.sheet_normalization import normalize_index_no
from models import AuditIssueDrawing, AuditResult, Drawing, JsonData
from services.audit.common import build_anchor
from services.layout_json_service import load_enriched_layout_json
from services.registration_service import (
    apply_image_evidence,
    build_pdf_anchor,
    ensure_drawing_registration,
    resolve_anchor_status,
)


INDEX_RE = re.compile(r"索引\s*([A-Za-z0-9_.-]+)")
DIMENSION_ID_RE = re.compile(r"标注ID\s*[:：]\s*([^\n，。,;；]+)")


def _parse_json(text: Optional[str]) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _normalize_search_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def _bbox_center_from_tuple(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _union_bboxes(boxes: List[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _build_cloud_highlight_region_from_pct_bbox(
    *,
    x0_pct: float,
    y0_pct: float,
    x1_pct: float,
    y1_pct: float,
    origin: str,
) -> Dict[str, Any]:
    x_min = min(x0_pct, x1_pct)
    y_min = min(y0_pct, y1_pct)
    raw_width = abs(x1_pct - x0_pct)
    raw_height = abs(y1_pct - y0_pct)
    base = max(raw_width, raw_height, 3.0)
    side = base * 1.35
    center_x = x_min + raw_width / 2.0
    center_y = y_min + raw_height / 2.0
    return {
        "shape": "cloud_rect",
        "bbox_pct": {
            "x": round(max(0.0, center_x - side / 2.0), 1),
            "y": round(max(0.0, center_y - side / 2.0), 1),
            "width": round(min(100.0, side), 1),
            "height": round(min(100.0, side), 1),
        },
        "origin": origin,
    }


def _find_pdf_in_png_dir(png_path: Optional[str]) -> Optional[Path]:
    if not png_path:
        return None
    folder = Path(png_path).expanduser().resolve().parent
    if not folder.exists():
        return None
    for candidate in sorted(folder.glob("*.pdf")):
        if candidate.is_file():
            return candidate
    return None


def _resolve_pdf_text_fallback_anchor(
    *,
    drawing: Drawing,
    sheet_no: Optional[str],
    index_no: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not drawing.png_path or drawing.page_index is None or not sheet_no or not index_no:
        return None

    pdf_path = _find_pdf_in_png_dir(drawing.png_path)
    if pdf_path is None:
        return None

    try:
        import fitz

        doc = fitz.open(pdf_path)
        try:
            page = doc.load_page(int(drawing.page_index))
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)
            if page_width <= 0 or page_height <= 0:
                return None

            sheet_norm = _normalize_search_text(sheet_no)
            index_norm = _normalize_search_text(index_no)
            candidates: List[tuple[float, Dict[str, Any]]] = []

            all_lines: List[Dict[str, Any]] = []
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if int(block.get("type", 0)) != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = "".join(str(span.get("text") or "") for span in spans).strip()
                    if not text:
                        continue
                    bbox = tuple(float(v) for v in line.get("bbox", (0, 0, 0, 0)))
                    all_lines.append(
                        {
                            "text": text,
                            "normalized": _normalize_search_text(text),
                            "bbox": bbox,
                        }
                    )

            index_lines = [line for line in all_lines if line["normalized"] == index_norm]
            sheet_lines = [line for line in all_lines if line["normalized"] == sheet_norm]
            title_lines = [
                line
                for line in all_lines
                if line not in index_lines
                and line not in sheet_lines
                and "SCALE" not in line["normalized"]
            ]

            for index_line in index_lines:
                index_center = _bbox_center_from_tuple(index_line["bbox"])
                for sheet_line in sheet_lines:
                    sheet_center = _bbox_center_from_tuple(sheet_line["bbox"])
                    if abs(index_center[0] - sheet_center[0]) > 120.0:
                        continue
                    if abs(index_center[1] - sheet_center[1]) > 60.0:
                        continue

                    related_boxes = [index_line["bbox"], sheet_line["bbox"]]
                    related_texts = [index_line["text"], sheet_line["text"]]
                    nearest_title = None
                    nearest_title_distance = 1e9
                    for title_line in title_lines:
                        title_center = _bbox_center_from_tuple(title_line["bbox"])
                        if abs(title_center[1] - index_center[1]) > 40.0:
                            continue
                        distance = abs(title_center[0] - index_center[0])
                        if distance < nearest_title_distance:
                            nearest_title_distance = distance
                            nearest_title = title_line
                    if nearest_title is not None and nearest_title_distance <= 180.0:
                        related_boxes.append(nearest_title["bbox"])
                        related_texts.append(nearest_title["text"])

                    union_bbox = _union_bboxes(related_boxes)
                    center_x, center_y = _bbox_center_from_tuple(union_bbox)
                    anchor = build_anchor(
                        role="source",
                        sheet_no=sheet_no,
                        grid="",
                        global_pct={
                            "x": round(center_x / page_width * 100.0, 1),
                            "y": round(center_y / page_height * 100.0, 1),
                        },
                        confidence=0.82,
                        origin="pdf_text",
                    )
                    if not isinstance(anchor, dict):
                        continue
                    anchor["pdf_text_bbox"] = {
                        "x0": round(union_bbox[0], 2),
                        "y0": round(union_bbox[1], 2),
                        "x1": round(union_bbox[2], 2),
                        "y1": round(union_bbox[3], 2),
                    }
                    anchor["pdf_text_lines"] = related_texts
                    anchor["highlight_region"] = _build_cloud_highlight_region_from_pct_bbox(
                        x0_pct=union_bbox[0] / page_width * 100.0,
                        y0_pct=union_bbox[1] / page_height * 100.0,
                        x1_pct=union_bbox[2] / page_width * 100.0,
                        y1_pct=union_bbox[3] / page_height * 100.0,
                        origin="pdf_text_bbox",
                    )
                    candidates.append((union_bbox[1], anchor))

            if not candidates:
                return None

            candidates.sort(key=lambda item: item[0])
            return candidates[-1][1]
        finally:
            doc.close()
    except Exception:
        return None


def extract_issue_index_no(result: AuditResult) -> Optional[str]:
    location = (result.location or "").strip()
    if not location:
        return None
    match = INDEX_RE.search(location)
    return match.group(1).strip() if match else None


def parse_issue_anchors(result: AuditResult) -> List[Dict[str, Any]]:
    payload = _parse_json(result.evidence_json)
    anchors = payload.get("anchors")
    if not isinstance(anchors, list):
        return []
    result_anchors: List[Dict[str, Any]] = []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        normalized = build_anchor(
            role=str(anchor.get("role") or "single").strip() or "single",
            sheet_no=str(anchor.get("sheet_no") or "").strip() or None,
            grid=str(anchor.get("grid") or "").strip() or None,
            global_pct=anchor.get("global_pct") if isinstance(anchor.get("global_pct"), dict) else None,
            confidence=anchor.get("confidence"),
            origin=str(anchor.get("origin") or "stored").strip() or "stored",
            highlight_region=anchor.get("highlight_region") if isinstance(anchor.get("highlight_region"), dict) else None,
            meta={
                key: value
                for key, value in anchor.items()
                if key
                not in {"role", "sheet_no", "grid", "global_pct", "confidence", "origin", "highlight_region"}
            },
        )
        if not normalized:
            continue
        result_anchors.append(normalized)
    return result_anchors


def resolve_drawing_for_sheet(
    project_id: str,
    sheet_no: Optional[str],
    db,
    *,
    prefer_data_version: Optional[int] = None,
    allow_replaced: bool = False,
) -> Optional[Drawing]:
    target = (sheet_no or "").strip()
    if not target:
        return None

    query = db.query(Drawing).filter(
        Drawing.project_id == project_id,
        Drawing.sheet_no == target,
    )
    if not allow_replaced:
        query = query.filter(Drawing.replaced_at == None)
    rows = query.all()
    if not rows:
        return None

    def sort_key(item: Drawing) -> tuple[int, int, int, int]:
        preferred = 1 if prefer_data_version is not None and item.data_version == prefer_data_version else 0
        active = 1 if item.replaced_at is None else 0
        matched = 1 if item.status == "matched" else 0
        version = int(item.data_version or 0)
        page_index = int(item.page_index or 999999)
        return (preferred, active, matched, version, -page_index)

    return sorted(rows, key=sort_key, reverse=True)[0]


def _preferred_data_version_from_anchor(anchor: Optional[Dict[str, Any]]) -> Optional[int]:
    if not isinstance(anchor, dict):
        return None
    value = anchor.get("data_version")
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def upsert_issue_drawing_match(
    *,
    result: AuditResult,
    match_side: str,
    drawing: Optional[Drawing],
    sheet_no: Optional[str],
    index_no: Optional[str],
    anchor: Optional[Dict[str, Any]],
    match_status: str,
    db,
) -> AuditIssueDrawing:
    record = (
        db.query(AuditIssueDrawing)
        .filter(
            AuditIssueDrawing.audit_result_id == result.id,
            AuditIssueDrawing.match_side == match_side,
        )
        .first()
    )
    if not record:
        record = AuditIssueDrawing(
            project_id=result.project_id,
            audit_result_id=result.id,
            audit_version=result.audit_version,
            match_side=match_side,
        )
        db.add(record)

    record.drawing_id = drawing.id if drawing else None
    record.drawing_data_version = drawing.data_version if drawing else None
    record.sheet_no = sheet_no or (drawing.sheet_no if drawing else None)
    record.sheet_name = drawing.sheet_name if drawing else None
    record.index_no = index_no
    record.anchor_json = json.dumps(anchor, ensure_ascii=False) if anchor else None
    record.match_status = match_status
    return record


def _load_json_for_sheet(
    project_id: str,
    sheet_no: str,
    db,
    *,
    prefer_data_version: Optional[int] = None,
) -> Optional[tuple[JsonData, Dict[str, Any]]]:
    row = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.sheet_no == sheet_no,
        )
        .all()
    )
    if not row:
        return None

    def sort_key(item: JsonData) -> tuple[int, int, int]:
        preferred = 1 if prefer_data_version is not None and item.data_version == prefer_data_version else 0
        latest = 1 if int(item.is_latest or 0) == 1 else 0
        version = int(item.data_version or 0)
        return (preferred, latest, version)

    selected = sorted(row, key=sort_key, reverse=True)[0]
    if not selected.json_path:
        return None
    return selected, load_enriched_layout_json(selected.json_path)


def _find_index_anchor_from_json(
    *,
    project_id: str,
    sheet_no: str,
    index_no: Optional[str],
    db,
) -> Optional[Dict[str, Any]]:
    if not sheet_no or not index_no:
        return None
    loaded = _load_json_for_sheet(project_id, sheet_no, db)
    if not loaded:
        return None
    row, payload = loaded
    if not payload:
        return None

    for item in payload.get("indexes", []) or []:
        if str(item.get("index_no") or "").strip() != str(index_no).strip():
            continue
        anchor = build_anchor(
            role="source",
            sheet_no=sheet_no,
            grid=str(item.get("grid") or "").strip(),
            global_pct=item.get("global_pct") if isinstance(item.get("global_pct"), dict) else None,
            confidence=1.0,
            origin="index",
        )
        if not isinstance(anchor, dict):
            return None
        position = item.get("position")
        if isinstance(position, (list, tuple)) and len(position) >= 2:
            try:
                anchor["layout_point"] = {"x": float(position[0]), "y": float(position[1])}
            except (TypeError, ValueError):
                pass
        layout_name = str(payload.get("layout_name") or "").strip()
        if layout_name:
            anchor["layout_name"] = layout_name
        if isinstance(item.get("highlight_region"), dict):
            anchor["highlight_region"] = item["highlight_region"]
        if row.data_version is not None:
            anchor["data_version"] = int(row.data_version)
        return anchor
    return None


def _extract_dimension_id_tokens(result: AuditResult) -> List[str]:
    description = str(result.description or "")
    matches = DIMENSION_ID_RE.findall(description)
    if not matches:
        return []

    tokens: List[str] = []
    seen = set()
    for match in matches:
        for token in re.findall(r"[A-Za-z0-9]+", str(match).upper()):
            key = normalize_index_no(token)
            if not key or key in seen:
                continue
            seen.add(key)
            tokens.append(token)
    return tokens


def _find_dimension_anchor_from_json(
    *,
    project_id: str,
    sheet_no: str,
    tokens: List[str],
    match_side: str,
    prefer_data_version: Optional[int],
    db,
) -> Optional[Dict[str, Any]]:
    if not sheet_no or not tokens:
        return None

    loaded = _load_json_for_sheet(
        project_id,
        sheet_no,
        db,
        prefer_data_version=prefer_data_version,
    )
    if not loaded:
        return None
    row, payload = loaded
    dimensions = payload.get("dimensions", []) or []
    if not dimensions:
        return None

    lookup: Dict[str, Dict[str, Any]] = {}
    for dim in dimensions:
        if not isinstance(dim, dict):
            continue
        dim_id = str(dim.get("id") or "").strip()
        dim_key = normalize_index_no(dim_id)
        if dim_key and dim_key not in lookup:
            lookup[dim_key] = dim

    for token in tokens:
        dim = lookup.get(normalize_index_no(token))
        if not dim:
            continue
        anchor = build_anchor(
            role=match_side,
            sheet_no=sheet_no,
            grid=str(dim.get("grid") or "").strip(),
            global_pct=dim.get("global_pct") if isinstance(dim.get("global_pct"), dict) else None,
            confidence=1.0,
            origin="dimension",
        )
        if not isinstance(anchor, dict):
            continue
        anchor["dimension_id"] = str(dim.get("id") or token).strip()
        if row.data_version is not None:
            anchor["data_version"] = int(row.data_version)
        return anchor
    return None


def _rebind_record_to_preferred_drawing(
    record: Optional[AuditIssueDrawing],
    *,
    anchor: Optional[Dict[str, Any]],
    db,
) -> Optional[AuditIssueDrawing]:
    if record is None:
        return None
    preferred_data_version = _preferred_data_version_from_anchor(anchor)
    if preferred_data_version is None:
        return record
    if int(record.drawing_data_version or 0) == preferred_data_version:
        return record

    drawing = resolve_drawing_for_sheet(
        record.project_id,
        record.sheet_no,
        db,
        prefer_data_version=preferred_data_version,
        allow_replaced=True,
    )
    if drawing is None:
        return record

    record.drawing_id = drawing.id
    record.drawing_data_version = drawing.data_version
    record.sheet_name = record.sheet_name or drawing.sheet_name
    return record


def _refresh_index_source_anchor_if_needed(
    result: AuditResult,
    record: AuditIssueDrawing,
    db,
) -> AuditIssueDrawing:
    if result.type != "index" or record.match_side != "source":
        return record

    fresh_anchor = _find_index_anchor_from_json(
        project_id=result.project_id,
        sheet_no=record.sheet_no or result.sheet_no_a or "",
        index_no=record.index_no or extract_issue_index_no(result),
        db=db,
    )
    if not fresh_anchor:
        return record

    if _parse_json(record.anchor_json) != fresh_anchor:
        record.anchor_json = json.dumps(fresh_anchor, ensure_ascii=False)
    record.index_no = record.index_no or extract_issue_index_no(result)
    return record


def _refresh_dimension_anchor_if_needed(
    result: AuditResult,
    record: AuditIssueDrawing,
    db,
) -> AuditIssueDrawing:
    if result.type != "dimension":
        return record

    existing_anchor = _parse_json(record.anchor_json)
    if existing_anchor.get("global_pct"):
        return record

    tokens = _extract_dimension_id_tokens(result)
    if not tokens:
        return record

    preferred_data_version = _preferred_data_version_from_anchor(existing_anchor)
    if preferred_data_version is None and record.drawing_data_version is not None:
        preferred_data_version = int(record.drawing_data_version)

    sheet_no = record.sheet_no or (
        result.sheet_no_a if record.match_side == "source" else result.sheet_no_b
    )
    fresh_anchor = _find_dimension_anchor_from_json(
        project_id=result.project_id,
        sheet_no=sheet_no or "",
        tokens=tokens,
        match_side=record.match_side,
        prefer_data_version=preferred_data_version,
        db=db,
    )
    if not fresh_anchor:
        return record

    if existing_anchor != fresh_anchor:
        record.anchor_json = json.dumps(fresh_anchor, ensure_ascii=False)
    if record.drawing_id:
        record.match_status = "matched"
    return record


def ensure_issue_drawing_matches(result: AuditResult, db) -> List[AuditIssueDrawing]:
    existing = (
        db.query(AuditIssueDrawing)
        .filter(AuditIssueDrawing.audit_result_id == result.id)
        .order_by(AuditIssueDrawing.match_side.asc())
        .all()
    )
    if existing:
        return existing

    anchors = parse_issue_anchors(result)
    index_no = extract_issue_index_no(result)
    persisted: List[AuditIssueDrawing] = []

    for match_side in ("source", "target"):
        anchor = next((item for item in anchors if str(item.get("role") or "").strip() == match_side), None)
        sheet_no = (
            (anchor or {}).get("sheet_no")
            or (result.sheet_no_a if match_side == "source" else result.sheet_no_b)
        )
        if not sheet_no:
            continue
        preferred_data_version = _preferred_data_version_from_anchor(anchor)
        drawing = resolve_drawing_for_sheet(
            result.project_id,
            sheet_no,
            db,
            prefer_data_version=preferred_data_version,
            allow_replaced=preferred_data_version is not None,
        )
        if drawing is None and match_side == "target":
            continue

        match_status = "matched" if drawing and anchor else ("missing_anchor" if drawing else "missing_drawing")
        persisted.append(
            upsert_issue_drawing_match(
                result=result,
                match_side=match_side,
                drawing=drawing,
                sheet_no=sheet_no,
                index_no=index_no,
                anchor=anchor,
                match_status=match_status,
                db=db,
            )
        )

    db.flush()
    return persisted


def get_issue_preview(result: AuditResult, db) -> Dict[str, Any]:
    records = ensure_issue_drawing_matches(result, db)
    refreshed_records = [
        _refresh_dimension_anchor_if_needed(
            result,
            _refresh_index_source_anchor_if_needed(result, record, db),
            db,
        )
        for record in records
    ]
    by_side = {record.match_side: record for record in refreshed_records}
    source = by_side.get("source")
    target = by_side.get("target")
    source_layout_anchor = _parse_json(source.anchor_json) if source and source.anchor_json else None
    target_layout_anchor = _parse_json(target.anchor_json) if target and target.anchor_json else None
    source = _rebind_record_to_preferred_drawing(source, anchor=source_layout_anchor, db=db)
    target = _rebind_record_to_preferred_drawing(target, anchor=target_layout_anchor, db=db)

    if source and source.drawing_id:
        source_drawing = db.query(Drawing).filter(Drawing.id == source.drawing_id).first()
        if not source_drawing:
            raise ValueError(f"历史图纸不存在: {source.drawing_id}")
        source_registration = ensure_drawing_registration(source_drawing, db)
        source_pdf_anchor = build_pdf_anchor(layout_anchor=source_layout_anchor, registration=source_registration)
        source_pdf_anchor = apply_image_evidence(pdf_anchor=source_pdf_anchor, drawing=source_drawing)
        source_anchor_status = resolve_anchor_status(
            layout_anchor=source_layout_anchor,
            pdf_anchor=source_pdf_anchor,
            registration=source_registration,
        )
        if source_anchor_status == "pdf_visual_mismatch" and result.type == "index":
            fallback_anchor = _resolve_pdf_text_fallback_anchor(
                drawing=source_drawing,
                sheet_no=source.sheet_no or result.sheet_no_a,
                index_no=source.index_no or extract_issue_index_no(result),
            )
            if fallback_anchor:
                source_pdf_anchor = fallback_anchor
                source_anchor_status = "pdf_text_fallback"
        source_payload = {
            "drawing_id": source_drawing.id,
            "drawing_data_version": source.drawing_data_version,
            "sheet_no": source.sheet_no,
            "sheet_name": source.sheet_name or source_drawing.sheet_name,
            "page_index": source_drawing.page_index,
            "match_status": source.match_status,
            "anchor": source_pdf_anchor or source_layout_anchor,
            "layout_anchor": source_layout_anchor,
            "pdf_anchor": source_pdf_anchor,
            "highlight_region": (
                (source_pdf_anchor or {}).get("highlight_region")
                or (source_layout_anchor or {}).get("highlight_region")
            ),
            "anchor_status": source_anchor_status,
            "registration_confidence": source_registration.registration_confidence if source_registration else None,
            "index_no": source.index_no,
        }
    else:
        source_payload = None

    if target and target.drawing_id:
        target_drawing = db.query(Drawing).filter(Drawing.id == target.drawing_id).first()
        if not target_drawing:
            raise ValueError(f"历史图纸不存在: {target.drawing_id}")
        target_registration = ensure_drawing_registration(target_drawing, db)
        target_pdf_anchor = build_pdf_anchor(layout_anchor=target_layout_anchor, registration=target_registration)
        target_pdf_anchor = apply_image_evidence(pdf_anchor=target_pdf_anchor, drawing=target_drawing)
        target_anchor_status = resolve_anchor_status(
            layout_anchor=target_layout_anchor,
            pdf_anchor=target_pdf_anchor,
            registration=target_registration,
        )
        target_payload = {
            "drawing_id": target_drawing.id,
            "drawing_data_version": target.drawing_data_version,
            "sheet_no": target.sheet_no,
            "sheet_name": target.sheet_name or target_drawing.sheet_name,
            "page_index": target_drawing.page_index,
            "match_status": target.match_status,
            "anchor": target_pdf_anchor or target_layout_anchor,
            "layout_anchor": target_layout_anchor,
            "pdf_anchor": target_pdf_anchor,
            "highlight_region": (
                (target_pdf_anchor or {}).get("highlight_region")
                or (target_layout_anchor or {}).get("highlight_region")
            ),
            "anchor_status": target_anchor_status,
            "registration_confidence": target_registration.registration_confidence if target_registration else None,
            "index_no": target.index_no,
        }
    else:
        target_payload = None

    missing_reason = None
    if result.type == "index" and (result.sheet_no_b or "").strip() and target_payload is None:
        missing_reason = "missing_target_drawing"

    return {
        "issue": {
            "id": result.id,
            "audit_version": result.audit_version,
            "type": result.type,
            "severity": result.severity,
            "sheet_no_a": result.sheet_no_a,
            "sheet_no_b": result.sheet_no_b,
            "location": result.location,
            "description": result.description,
        },
        "source": source_payload,
        "target": target_payload,
        "missing_reason": missing_reason,
    }
