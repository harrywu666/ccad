"""
审核服务模块
提供索引核对、尺寸核对、材料核对功能
"""

import json
import re
import io
import asyncio
import hashlib
import logging
import os
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from models import JsonData, AuditResult, AuditRun, Catalog, Drawing, Project
from domain.sheet_normalization import normalize_index_no, normalize_sheet_no
from services.coordinate_service import cad_to_global_pct, enrich_json_with_coordinates
from services.storage_path_service import resolve_project_dir

logger = logging.getLogger(__name__)


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
    """
    三线匹配：以锁定目录为基准，汇总目录 / PNG / JSON 的一对一状态。

    Returns:
        {
          "project_id": str,
          "summary": {total, ready, missing_png, missing_json, missing_all},
          "items": [...]
        }
    """
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
        unmatched_json_items.append({
            "id": jd.id,
            "sheet_no": jd.sheet_no,
            "layout_name": getattr(jd, "layout_name", None),
            "source_dwg": getattr(jd, "source_dwg", None),
            "thumbnail_path": getattr(jd, "thumbnail_path", None),
            "json_path": jd.json_path,
            "data_version": jd.data_version,
            "status": jd.status,
            "created_at": jd.created_at.isoformat() if isinstance(jd.created_at, datetime) else None,
        })

    return {
        "project_id": project_id,
        "summary": summary,
        "items": items,
        "unmatched_jsons": unmatched_json_items,
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_anchor(
    *,
    role: str,
    sheet_no: Optional[str],
    grid: Optional[str] = None,
    global_pct: Optional[Dict[str, Any]] = None,
    confidence: Optional[float] = None,
    origin: str = "inferred",
) -> Optional[Dict[str, Any]]:
    anchor: Dict[str, Any] = {
        "role": role,
        "sheet_no": (sheet_no or "").strip(),
        "grid": (grid or "").strip(),
        "origin": origin,
    }

    if global_pct and isinstance(global_pct, dict):
        x = _safe_float(global_pct.get("x"))
        y = _safe_float(global_pct.get("y"))
        if x is not None and y is not None:
            anchor["global_pct"] = {
                "x": round(max(0.0, min(100.0, x)), 1),
                "y": round(max(0.0, min(100.0, y)), 1),
            }

    if confidence is not None:
        c = _safe_float(confidence)
        if c is not None:
            anchor["confidence"] = round(max(0.0, min(1.0, c)), 3)

    if not anchor["sheet_no"]:
        return None
    if "global_pct" not in anchor and not anchor["grid"]:
        return None
    return anchor


def _to_evidence_json(
    anchors: List[Dict[str, Any]],
    *,
    pair_id: Optional[str] = None,
    unlocated_reason: Optional[str] = None,
) -> Optional[str]:
    payload: Dict[str, Any] = {"anchors": anchors or []}
    if pair_id:
        payload["pair_id"] = pair_id
    if unlocated_reason:
        payload["unlocated_reason"] = unlocated_reason
    return json.dumps(payload, ensure_ascii=False)


def _issue_index(
    project_id: str,
    audit_version: int,
    severity: str,
    sheet_no_a: Optional[str],
    sheet_no_b: Optional[str],
    location: str,
    description: str,
    evidence_json: Optional[str] = None,
) -> AuditResult:
    return AuditResult(
        project_id=project_id,
        audit_version=audit_version,
        type="index",
        severity=severity,
        sheet_no_a=sheet_no_a,
        sheet_no_b=sheet_no_b,
        location=location,
        description=description,
        evidence_json=evidence_json,
    )


def audit_indexes(
    project_id: str,
    audit_version: int,
    db,
    source_sheet_filters: Optional[List[str]] = None,
) -> List[AuditResult]:
    """
    索引核对：检测断链、反向缺失、孤立索引

    Args:
        project_id: 项目ID
        audit_version: 审核版本号
        db: 数据库会话

    Returns:
        审核结果列表
    """
    allowed_source_keys: Optional[set[str]] = None
    if source_sheet_filters:
        allowed_source_keys = {
            normalize_sheet_no(item)
            for item in source_sheet_filters
            if normalize_sheet_no(item)
        }
        if not allowed_source_keys:
            return []

    json_list = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .all()
    )

    sheet_map: Dict[str, str] = {}
    sheet_index_defs: Dict[str, set[str]] = defaultdict(set)
    forward_links: List[Dict[str, Any]] = []
    orphan_candidates: List[Dict[str, Any]] = []
    sheet_index_anchor_map: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    for json_data in json_list:
        json_path = json_data.json_path or ""
        if not json_path:
            continue

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        data = enrich_json_with_coordinates(data)

        raw_sheet_no = (json_data.sheet_no or data.get("sheet_no") or "").strip()
        if not raw_sheet_no:
            continue
        src_key = normalize_sheet_no(raw_sheet_no)
        if not src_key:
            continue
        sheet_map.setdefault(src_key, raw_sheet_no)

        indexes = data.get("indexes", []) or []
        for idx in indexes:
            raw_index_no = str(idx.get("index_no", "") or "").strip()
            raw_target_sheet = str(idx.get("target_sheet", "") or "").strip()
            pos = idx.get("position", [])
            idx_key = normalize_index_no(raw_index_no)
            tgt_key = normalize_sheet_no(raw_target_sheet)
            source_anchor = _build_anchor(
                role="source",
                sheet_no=raw_sheet_no,
                grid=str(idx.get("grid") or "").strip(),
                global_pct=idx.get("global_pct") if isinstance(idx.get("global_pct"), dict) else None,
                confidence=1.0,
                origin="index",
            )

            if idx_key:
                sheet_index_defs[src_key].add(idx_key)
                if source_anchor and idx_key not in sheet_index_anchor_map[src_key]:
                    sheet_index_anchor_map[src_key][idx_key] = source_anchor

            if not idx_key and not tgt_key:
                continue

            row = {
                "source_raw": raw_sheet_no,
                "source_key": src_key,
                "index_raw": raw_index_no,
                "index_key": idx_key,
                "target_raw": raw_target_sheet,
                "target_key": tgt_key,
                "position": pos,
                "source_anchor": source_anchor,
            }
            if tgt_key:
                forward_links.append(row)
            elif idx_key:
                orphan_candidates.append(row)

    issues: List[AuditResult] = []
    existing_sheets = set(sheet_map.keys())
    referenced_targets = {
        (item["target_key"], item["index_key"])
        for item in forward_links
        if item["target_key"] and item["index_key"]
    }
    reverse_link_keys = {
        (item["source_key"], item["target_key"])
        for item in forward_links
        if item["source_key"] and item["target_key"]
    }

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        tgt_key = rel["target_key"]
        if tgt_key not in existing_sheets:
            anchors = [rel["source_anchor"]] if rel.get("source_anchor") else []
            issue = _issue_index(
                project_id=project_id,
                audit_version=audit_version,
                severity="error",
                sheet_no_a=rel["source_raw"],
                sheet_no_b=rel["target_raw"] or None,
                location=f"索引{rel['index_raw'] or '?'}",
                description=(
                    f"图纸{rel['source_raw']}中的索引{rel['index_raw'] or '?'}"
                    f" 指向 {rel['target_raw'] or '未知图号'}，但目录/数据中不存在该目标图。"
                ),
                evidence_json=_to_evidence_json(anchors, unlocated_reason=None if anchors else "missing_target_sheet"),
            )
            db.add(issue)
            issues.append(issue)

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        tgt_key = rel["target_key"]
        idx_key = rel["index_key"]
        if not tgt_key or tgt_key not in existing_sheets or not idx_key:
            continue
        if idx_key not in sheet_index_defs.get(tgt_key, set()):
            target_raw = sheet_map.get(tgt_key, rel["target_raw"] or "")
            anchors = [rel["source_anchor"]] if rel.get("source_anchor") else []
            issue = _issue_index(
                project_id=project_id,
                audit_version=audit_version,
                severity="error",
                sheet_no_a=rel["source_raw"],
                sheet_no_b=target_raw or rel["target_raw"] or None,
                location=f"索引{rel['index_raw'] or '?'}",
                description=(
                    f"图纸{rel['source_raw']}中的索引{rel['index_raw'] or '?'} 指向 {target_raw or rel['target_raw'] or '目标图'}，"
                    "但目标图中未找到同编号索引。"
                ),
                evidence_json=_to_evidence_json(anchors, unlocated_reason=None if anchors else "missing_target_index_no"),
            )
            db.add(issue)
            issues.append(issue)

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        src_key = rel["source_key"]
        tgt_key = rel["target_key"]
        if not src_key or not tgt_key or src_key == tgt_key:
            continue
        if tgt_key not in existing_sheets:
            continue
        if (tgt_key, src_key) in reverse_link_keys:
            continue
        target_raw = sheet_map.get(tgt_key, rel["target_raw"] or "")
        anchors: List[Dict[str, Any]] = []
        if rel.get("source_anchor"):
            anchors.append(rel["source_anchor"])
        target_anchor = sheet_index_anchor_map.get(tgt_key, {}).get(rel["index_key"] or "")
        if target_anchor:
            target_anchor = dict(target_anchor)
            target_anchor["role"] = "target"
            anchors.append(target_anchor)
        issue = _issue_index(
            project_id=project_id,
            audit_version=audit_version,
            severity="warning",
            sheet_no_a=rel["source_raw"],
            sheet_no_b=target_raw or rel["target_raw"] or None,
            location=f"索引{rel['index_raw'] or '?'}",
            description=(
                f"图纸{rel['source_raw']}指向{target_raw or rel['target_raw'] or '目标图'}，"
                f"但未发现{target_raw or rel['target_raw'] or '目标图'}反向指向{rel['source_raw']}，请确认索引链闭合性。"
            ),
            evidence_json=_to_evidence_json(anchors, unlocated_reason=None if anchors else "missing_reverse_link"),
        )
        db.add(issue)
        issues.append(issue)

    for orphan in orphan_candidates:
        if allowed_source_keys is not None and orphan["source_key"] not in allowed_source_keys:
            continue
        pair = (orphan["source_key"], orphan["index_key"])
        if pair in referenced_targets:
            continue
        anchors = [orphan["source_anchor"]] if orphan.get("source_anchor") else []
        issue = _issue_index(
            project_id=project_id,
            audit_version=audit_version,
            severity="warning",
            sheet_no_a=orphan["source_raw"],
            sheet_no_b=None,
            location=f"索引{orphan['index_raw'] or '?'}",
            description=(
                f"图纸{orphan['source_raw']}中的索引{orphan['index_raw'] or '?'} 未标注目标图号，且未被其他图纸引用，可能是孤立索引。"
            ),
            evidence_json=_to_evidence_json(anchors, unlocated_reason=None if anchors else "orphan_index_without_target"),
        )
        db.add(issue)
        issues.append(issue)

    db.commit()
    return issues


def audit_dimensions(
    project_id: str,
    audit_version: int,
    db,
    pair_filters: Optional[List[Tuple[str, str]]] = None,
) -> List[AuditResult]:
    """兼容入口：委托到模块化尺寸审核实现。"""
    from services.audit.dimension_audit import audit_dimensions as run_dimension_audit

    return run_dimension_audit(project_id, audit_version, db, pair_filters=pair_filters)


def audit_materials(
    project_id: str,
    audit_version: int,
    db,
    sheet_filters: Optional[List[str]] = None,
) -> List[AuditResult]:
    """兼容入口：委托到模块化材料审核实现。"""
    from services.audit.material_audit import audit_materials as run_material_audit

    return run_material_audit(project_id, audit_version, db, sheet_filters=sheet_filters)
