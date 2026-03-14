"""审核服务：仅保留三线匹配（目录/PNG/JSON）能力。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import AuditResult, AuditRun, Catalog, Drawing, JsonData, Project


def _pick_latest_drawing(rows: List[Drawing]) -> Optional[Drawing]:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            row.data_version or 0,
            1 if row.png_path else 0,
            1 if row.status == "matched" else 0,
            -(row.page_index if row.page_index is not None else 10**9),
        ),
    )


def _pick_latest_json(rows: List[JsonData]) -> Optional[JsonData]:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            row.data_version or 0,
            1 if row.json_path else 0,
            1 if row.status == "matched" else 0,
            row.created_at.timestamp() if row.created_at else 0,
        ),
    )


def _is_placeholder_json(row: Optional[JsonData]) -> bool:
    if not row:
        return False
    summary = str(row.summary or "").strip()
    if summary.startswith("占位JSON"):
        return True
    json_path = str(row.json_path or "").strip()
    if not json_path:
        return False
    return Path(json_path).name.startswith("placeholder_")


def _derive_project_status(summary: Dict[str, int]) -> str:
    total = summary["total"]
    ready = summary["ready"]
    missing_all = summary["missing_all"]

    if total == 0:
        return "new"
    if ready == total:
        return "ready"
    if missing_all == total:
        return "catalog_locked"
    return "matching"


def _derive_audit_override_status(project_id: str, db) -> Optional[str]:  # noqa: ANN001
    running_run = (
        db.query(AuditRun.id)
        .filter(
            AuditRun.project_id == project_id,
            AuditRun.status == "running",
        )
        .first()
    )
    if running_run:
        return "auditing"

    done_run = (
        db.query(AuditRun.id)
        .filter(
            AuditRun.project_id == project_id,
            AuditRun.status == "done",
        )
        .first()
    )
    if done_run:
        return "done"

    any_result = (
        db.query(AuditResult.id)
        .filter(AuditResult.project_id == project_id)
        .first()
    )
    if any_result:
        return "done"

    return None


def match_three_lines(project_id: str, db) -> Dict[str, Any]:
    """三线匹配：按目录锁定项汇总 PNG/JSON 就绪状态。"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")

    catalogs = (
        db.query(Catalog)
        .filter(
            Catalog.project_id == project_id,
            Catalog.status == "locked",
        )
        .order_by(Catalog.sort_order.asc())
        .all()
    )

    summary = {
        "total": len(catalogs),
        "ready": 0,
        "missing_png": 0,
        "missing_json": 0,
        "missing_all": 0,
    }

    if not catalogs:
        next_status = _derive_audit_override_status(project_id, db) or _derive_project_status(summary)
        if project.status != next_status:
            project.status = next_status
            db.commit()
        return {
            "project_id": project_id,
            "summary": summary,
            "items": [],
        }

    catalog_ids = [item.id for item in catalogs]

    drawing_rows = (
        db.query(Drawing)
        .filter(
            Drawing.project_id == project_id,
            Drawing.replaced_at == None,
            Drawing.catalog_id.in_(catalog_ids),
        )
        .all()
    )
    json_rows = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
            JsonData.catalog_id.in_(catalog_ids),
        )
        .all()
    )

    drawing_map: Dict[str, List[Drawing]] = {}
    for row in drawing_rows:
        if not row.catalog_id:
            continue
        drawing_map.setdefault(row.catalog_id, []).append(row)

    json_map: Dict[str, List[JsonData]] = {}
    for row in json_rows:
        if not row.catalog_id:
            continue
        json_map.setdefault(row.catalog_id, []).append(row)

    items: List[Dict[str, Any]] = []
    for catalog in catalogs:
        drawing = _pick_latest_drawing(drawing_map.get(catalog.id, []))
        json_data = _pick_latest_json(json_map.get(catalog.id, []))

        has_png = bool(drawing and drawing.png_path)
        is_placeholder_json = _is_placeholder_json(json_data)
        has_json = bool(json_data and json_data.json_path and not is_placeholder_json)

        if has_png and has_json:
            line_status = "ready"
            summary["ready"] += 1
        elif (not has_png) and has_json:
            line_status = "missing_png"
            summary["missing_png"] += 1
        elif has_png and (not has_json):
            line_status = "missing_json"
            summary["missing_json"] += 1
        else:
            line_status = "missing_all"
            summary["missing_all"] += 1

        items.append(
            {
                "catalog_id": catalog.id,
                "sheet_no": catalog.sheet_no,
                "sheet_name": catalog.sheet_name,
                "sort_order": catalog.sort_order,
                "status": line_status,
                "drawing": {
                    "id": drawing.id,
                    "sheet_no": drawing.sheet_no,
                    "sheet_name": drawing.sheet_name,
                    "png_path": drawing.png_path,
                    "page_index": drawing.page_index,
                    "data_version": drawing.data_version,
                    "status": drawing.status,
                }
                if drawing
                else None,
                "json": {
                    "id": json_data.id,
                    "sheet_no": json_data.sheet_no,
                    "json_path": json_data.json_path,
                    "data_version": json_data.data_version,
                    "status": json_data.status,
                    "summary": json_data.summary,
                    "is_placeholder": is_placeholder_json,
                    "created_at": (
                        json_data.created_at.isoformat() if isinstance(json_data.created_at, datetime) else None
                    ),
                }
                if json_data
                else None,
            }
        )

    next_status = _derive_audit_override_status(project_id, db) or _derive_project_status(summary)
    if project.status != next_status:
        project.status = next_status
        db.commit()

    unmatched_jsons = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
            JsonData.status == "unmatched",
        )
        .all()
    )
    unmatched_json_items = []
    for jd in unmatched_jsons:
        unmatched_json_items.append(
            {
                "id": jd.id,
                "sheet_no": jd.sheet_no,
                "layout_name": getattr(jd, "layout_name", None),
                "source_dwg": getattr(jd, "source_dwg", None),
                "thumbnail_path": getattr(jd, "thumbnail_path", None),
                "json_path": jd.json_path,
                "data_version": jd.data_version,
                "status": jd.status,
                "created_at": jd.created_at.isoformat() if isinstance(jd.created_at, datetime) else None,
            }
        )

    return {
        "project_id": project_id,
        "summary": summary,
        "items": items,
        "unmatched_jsons": unmatched_json_items,
    }


__all__ = ["match_three_lines"]
