"""Issue preview persistence and lookup helpers."""

from __future__ import annotations

import json
import re
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


def extract_issue_index_no(result: AuditResult) -> Optional[str]:
    location = (result.location or "").strip()
    if not location:
        return None
    match = INDEX_RE.search(location)
    return match.group(1).strip() if match else None


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_layout_point(value: Any) -> Optional[Dict[str, float]]:
    if isinstance(value, dict):
        x = _safe_float(value.get("x"))
        y = _safe_float(value.get("y"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x = _safe_float(value[0])
        y = _safe_float(value[1])
    else:
        return None
    if x is None or y is None:
        return None
    return {"x": round(x, 3), "y": round(y, 3)}


def _normalize_layout_bbox(value: Any) -> Optional[List[float]]:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    x1 = _safe_float(value[0])
    y1 = _safe_float(value[1])
    x2 = _safe_float(value[2])
    y2 = _safe_float(value[3])
    if x1 is None or y1 is None or x2 is None or y2 is None:
        return None
    left, right = sorted((x1, x2))
    bottom, top = sorted((y1, y2))
    if right <= left or top <= bottom:
        return None
    return [round(left, 3), round(bottom, 3), round(right, 3), round(top, 3)]


def parse_issue_anchors(result: AuditResult) -> List[Dict[str, Any]]:
    payload = _parse_json(result.evidence_json)
    anchors = payload.get("anchors")
    if not isinstance(anchors, list):
        return []
    result_anchors: List[Dict[str, Any]] = []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        role = str(anchor.get("role") or "single").strip() or "single"
        sheet_no = str(anchor.get("sheet_no") or "").strip() or None
        if not sheet_no:
            continue
        layout_point = _normalize_layout_point(anchor.get("layout_point"))
        layout_bbox = _normalize_layout_bbox(anchor.get("layout_bbox"))
        extra_meta = {
            key: value
            for key, value in anchor.items()
            if key
            not in {
                "role",
                "sheet_no",
                "grid",
                "global_pct",
                "confidence",
                "origin",
                "highlight_region",
                "layout_point",
                "layout_bbox",
            }
            and value is not None
        }
        if layout_point is not None:
            extra_meta["layout_point"] = layout_point
        if layout_bbox is not None:
            extra_meta["layout_bbox"] = layout_bbox
        normalized = build_anchor(
            role=role,
            sheet_no=sheet_no,
            grid=str(anchor.get("grid") or "").strip() or None,
            global_pct=anchor.get("global_pct") if isinstance(anchor.get("global_pct"), dict) else None,
            confidence=anchor.get("confidence"),
            origin=str(anchor.get("origin") or "stored").strip() or "stored",
            highlight_region=anchor.get("highlight_region") if isinstance(anchor.get("highlight_region"), dict) else None,
            meta=extra_meta,
        )
        if normalized is None and layout_point is not None:
            normalized = {
                "role": role,
                "sheet_no": sheet_no,
                "grid": str(anchor.get("grid") or "").strip(),
                "origin": str(anchor.get("origin") or "stored").strip() or "stored",
                "layout_point": layout_point,
            }
            confidence = _safe_float(anchor.get("confidence"))
            if confidence is not None:
                normalized["confidence"] = round(max(0.0, min(1.0, confidence)), 3)
            if isinstance(anchor.get("highlight_region"), dict):
                normalized["highlight_region"] = anchor.get("highlight_region")
            for key, value in extra_meta.items():
                if key not in normalized and value is not None:
                    normalized[key] = value
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
