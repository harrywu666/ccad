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
from models import JsonData, AuditResult, Catalog, Drawing, Project
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
        next_status = _derive_project_status(summary)
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
        has_json = bool(json_data and json_data.json_path)

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
                    "created_at": (
                        json_data.created_at.isoformat() if isinstance(json_data.created_at, datetime) else None
                    ),
                }
                if json_data
                else None,
            }
        )

    next_status = _derive_project_status(summary)
    if project.status != next_status:
        project.status = next_status
        db.commit()

    return {
        "project_id": project_id,
        "summary": summary,
        "items": items,
    }


_CIRCLED_NUM_MAP = str.maketrans(
    {
        "①": "1",
        "②": "2",
        "③": "3",
        "④": "4",
        "⑤": "5",
        "⑥": "6",
        "⑦": "7",
        "⑧": "8",
        "⑨": "9",
        "⑩": "10",
        "⑪": "11",
        "⑫": "12",
        "⑬": "13",
        "⑭": "14",
        "⑮": "15",
        "⑯": "16",
        "⑰": "17",
        "⑱": "18",
        "⑲": "19",
        "⑳": "20",
    }
)


def _norm_sheet_no(value: Optional[str]) -> str:
    if not value:
        return ""
    s = str(value).strip().upper()
    s = s.translate(_CIRCLED_NUM_MAP)
    s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", s)
    return s


def _norm_index_no(value: Optional[str]) -> str:
    if not value:
        return ""
    s = str(value).strip().upper()
    s = s.translate(_CIRCLED_NUM_MAP)
    s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", s)
    return s


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
            _norm_sheet_no(item)
            for item in source_sheet_filters
            if _norm_sheet_no(item)
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

    # sheet_map: 规范化图号 -> 原始图号
    sheet_map: Dict[str, str] = {}
    # sheet_index_defs: 每张图上的索引编号集合（用于判断目标图是否存在同编号）
    sheet_index_defs: Dict[str, set[str]] = defaultdict(set)
    # forward_links: 带目标图的索引关系
    forward_links: List[Dict[str, Any]] = []
    # orphan_candidates: 只有编号没有目标图的索引（候选孤立索引）
    orphan_candidates: List[Dict[str, Any]] = []
    # 每张图每个索引编号的定位锚点（用于目标图反查）
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
        src_key = _norm_sheet_no(raw_sheet_no)
        if not src_key:
            continue
        sheet_map.setdefault(src_key, raw_sheet_no)

        indexes = data.get("indexes", []) or []
        for idx in indexes:
            raw_index_no = str(idx.get("index_no", "") or "").strip()
            raw_target_sheet = str(idx.get("target_sheet", "") or "").strip()
            pos = idx.get("position", [])
            idx_key = _norm_index_no(raw_index_no)
            tgt_key = _norm_sheet_no(raw_target_sheet)
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

            # 无编号无目标，属于噪声，跳过
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
    # (目标图, 编号) 被其他图引用，用于判断孤立索引
    referenced_targets = {
        (item["target_key"], item["index_key"])
        for item in forward_links
        if item["target_key"] and item["index_key"]
    }
    # 反向索引存在性：target -> source 是否也存在
    reverse_link_keys = {
        (item["source_key"], item["target_key"])
        for item in forward_links
        if item["source_key"] and item["target_key"]
    }

    # 规则1：断链（目标图不存在）
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

    # 规则2：目标图存在，但缺少对应编号（编号断链）
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

    # 规则3：反向缺失（A -> B 存在，但 B -> A 不存在）
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

    # 规则4：孤立索引（仅编号，无目标，且无人引用）
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
    """
    尺寸核对：按文档六执行 5 图输入（全图+4象限），严格调用Kimi（无规则兜底）
    
    Args:
        project_id: 项目ID
        audit_version: 审核版本号
        db: 数据库会话
    
    Returns:
        审核结果列表
    """
    from services.kimi_service import call_kimi

    def _read_json(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _find_pdf_in_png_dir(png_path: str) -> Optional[str]:
        if not png_path:
            return None
        try:
            folder = Path(png_path).expanduser().resolve().parent
        except Exception:
            return None
        if not folder.exists() or not folder.is_dir():
            return None
        pdfs = sorted(folder.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not pdfs:
            return None
        return str(pdfs[0])

    def _collect_page_asset_map(rows: List[Drawing]) -> Dict[str, Dict[str, Any]]:
        asset_map: Dict[str, Dict[str, Any]] = {}
        by_key: Dict[str, List[Drawing]] = defaultdict(list)
        for row in rows:
            if not row.sheet_no:
                continue
            by_key[_norm_sheet_no(row.sheet_no)].append(row)
        for key, items in by_key.items():
            items_sorted = sorted(
                items,
                key=lambda x: (x.data_version or 0, 1 if x.status == "matched" else 0),
                reverse=True,
            )
            latest = items_sorted[0]
            asset_map[key] = {
                "png_path": latest.png_path,
                "page_index": latest.page_index,
                "pdf_path": _find_pdf_in_png_dir(latest.png_path or ""),
            }
        return asset_map

    def _dimension_global_point(dim: Dict[str, Any], model_range: Dict[str, Any]) -> Optional[Dict[str, float]]:
        gp = dim.get("global_pct")
        if isinstance(gp, dict) and gp.get("x") is not None and gp.get("y") is not None:
            try:
                return {"x": float(gp["x"]), "y": float(gp["y"])}
            except (TypeError, ValueError):
                pass
        pos = dim.get("text_position") or dim.get("defpoint")
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            return None
        try:
            x = float(pos[0])
            y = float(pos[1])
        except (TypeError, ValueError):
            return None
        pct_x, pct_y = cad_to_global_pct(x, y, model_range or {})
        return {"x": pct_x, "y": pct_y}

    def _compact_dimensions(dims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        compact: List[Dict[str, Any]] = []
        for d in dims[:120]:
            gp = d.get("global_pct") if isinstance(d.get("global_pct"), dict) else None
            compact.append(
                {
                    "id": d.get("id"),
                    "value": d.get("value"),
                    "display_text": d.get("display_text"),
                    "layer": d.get("layer"),
                    "grid": d.get("grid"),
                    "global_pct": {"x": gp.get("x"), "y": gp.get("y")} if gp else None,
                    "in_quadrants": d.get("in_quadrants"),
                }
            )
        return compact

    def _resize_to_4k(img):
        from PIL import Image
        target_w = 3840
        if img.width <= target_w:
            return img
        ratio = target_w / img.width
        return img.resize((target_w, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)

    def _draw_grid(img):
        from PIL import ImageDraw, ImageFont
        grid_cols = 24
        grid_rows = 17
        labels = "ABCDEFGHIJKLMNOPQRSTUVWX"
        draw = ImageDraw.Draw(img)
        w, h = img.size
        col_w = w / grid_cols
        row_h = h / grid_rows
        color = (220, 220, 220)

        for i in range(1, grid_cols):
            x = int(i * col_w)
            draw.line([(x, 0), (x, h)], fill=color, width=1)
        for j in range(1, grid_rows):
            y = int(j * row_h)
            draw.line([(0, y), (w, y)], fill=color, width=1)

        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 18)
        except Exception:
            font = ImageFont.load_default()

        for i in range(grid_cols):
            text = labels[i]
            x = int((i + 0.5) * col_w) - 6
            draw.text((x, 4), text, fill=(120, 120, 120), font=font)
            draw.text((x, h - 24), text, fill=(120, 120, 120), font=font)
        for j in range(grid_rows):
            text = str(j + 1)
            y = int((j + 0.5) * row_h) - 8
            draw.text((4, y), text, fill=(120, 120, 120), font=font)
            draw.text((w - 20, y), text, fill=(120, 120, 120), font=font)
        return img

    def _pdf_page_to_5images(pdf_path: str, page_index: int, overlap: float = 0.20) -> Dict[str, bytes]:
        from PIL import Image
        import fitz

        doc = fitz.open(pdf_path)
        try:
            page = doc.load_page(page_index)

            # 文档六：图1全图 150DPI
            mat_low = fitz.Matrix(150 / 72, 150 / 72)
            pix_low = page.get_pixmap(matrix=mat_low)
            img_full = Image.open(io.BytesIO(pix_low.tobytes("png"))).convert("RGB")
            full = _draw_grid(_resize_to_4k(img_full))

            # 文档六：图2-5象限 300DPI
            mat_high = fitz.Matrix(300 / 72, 300 / 72)
            pix_high = page.get_pixmap(matrix=mat_high)
            img_src = Image.open(io.BytesIO(pix_high.tobytes("png"))).convert("RGB")

            w, h = img_src.size
            cx = w // 2
            cy = h // 2
            ox = int(w * overlap / 2.0)
            oy = int(h * overlap / 2.0)
            boxes = {
                "top_left": (0, 0, cx + ox, cy + oy),
                "top_right": (cx - ox, 0, w, cy + oy),
                "bottom_left": (0, cy - oy, cx + ox, h),
                "bottom_right": (cx - ox, cy - oy, w, h),
            }

            def _to_png_bytes(source) -> bytes:
                buf = io.BytesIO()
                source.save(buf, format="PNG")
                return buf.getvalue()

            qbytes: Dict[str, bytes] = {}
            for name, box in boxes.items():
                crop = _resize_to_4k(img_src.crop(box))
                qbytes[name] = _to_png_bytes(crop)

            return {
                "full": _to_png_bytes(full),
                "top_left": qbytes["top_left"],
                "top_right": qbytes["top_right"],
                "bottom_left": qbytes["bottom_left"],
                "bottom_right": qbytes["bottom_right"],
            }
        finally:
            doc.close()

    def _build_single_sheet_prompt(sheet_no: str, sheet_name: str, dims_compact: List[Dict[str, Any]]) -> str:
        return (
            f"对图纸（{sheet_no} {sheet_name}）做尺寸语义分析。\n"
            "你将收到5张图：图1全图（带网格），图2-5为四个高清象限（20%重叠）。\n"
            "请按“先定位，再理解语义”执行：先在图1找网格位置，再去对应象限图确认。\n"
            "以下是DWG提取的精确尺寸数据（无需重新OCR）：\n"
            f"{json.dumps(dims_compact, ensure_ascii=False)}\n"
            "请输出每条尺寸的语义解析结果，只返回JSON数组，不要解释。\n"
            "格式："
            "[{\"id\":\"\",\"semantic\":\"\",\"location_desc\":\"\",\"dim_type\":\"\",\"value\":0,"
            "\"grid\":\"\",\"component\":\"\",\"confidence\":0.0,\"evidence\":{\"grid\":\"\",\"why\":\"\"}}]"
        )

    def _build_pair_compare_prompt(
        a_sheet_no: str,
        a_sheet_name: str,
        a_semantic: List[Dict[str, Any]],
        b_sheet_no: str,
        b_sheet_name: str,
        b_semantic: List[Dict[str, Any]],
    ) -> str:
        return (
            "请对比两张图的尺寸语义列表，找出同一构件/空间的尺寸不一致项。\n"
            "你必须按流程执行：先定位 -> 再配对 -> 再核对。\n"
            "规则：\n"
            "1) 先根据 semantic/component/grid 选候选，不要直接猜。\n"
            "2) 只有定位证据充分时才输出问题；证据不足就不要输出。\n"
            "3) 输出必须带证据字段，便于人工复核。\n"
            f"A图：{a_sheet_no} {a_sheet_name}\n"
            f"A图语义数据：{json.dumps(a_semantic, ensure_ascii=False)}\n"
            f"B图：{b_sheet_no} {b_sheet_name}\n"
            f"B图语义数据：{json.dumps(b_semantic, ensure_ascii=False)}\n"
            "只返回问题JSON数组，无问题返回[]。\n"
            "格式：[{"
            "\"位置描述\":\"\","
            "\"A图号\":\"\",\"B图号\":\"\","
            "\"A值\":0,\"B值\":0,\"差值\":0,"
            "\"source_grid\":\"\",\"target_grid\":\"\","
            "\"source_dim_id\":\"\",\"target_dim_id\":\"\","
            "\"index_hint\":\"\","
            "\"confidence\":0.0,"
            "\"description\":\"\","
            "\"evidence\":{"
            "\"source_sheet_no\":\"\",\"target_sheet_no\":\"\","
            "\"source_grid\":\"\",\"target_grid\":\"\","
            "\"source_dim_id\":\"\",\"target_dim_id\":\"\","
            "\"confidence\":0.0,\"why\":\"\""
            "}"
            "}]"
        )

    def _read_int_env(name: str, default: int, *, low: int = 1, high: int = 64) -> int:
        raw = os.getenv(name, str(default))
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    def _canonical_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _sha256_parts(parts: List[str]) -> str:
        digest = hashlib.sha256()
        for part in parts:
            digest.update((part or "").encode("utf-8", errors="ignore"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _file_sig(path: Optional[str]) -> str:
        if not path:
            return "missing"
        p = Path(path).expanduser()
        if not p.exists():
            return f"missing:{path}"
        st = p.stat()
        return f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}"

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")

    def _cache_dir_for_project() -> Path:
        root = resolve_project_dir(project, ensure=True) / "cache" / "dimension-v1"
        root.mkdir(parents=True, exist_ok=True)
        return root

    cache_dir = _cache_dir_for_project()

    def _cache_file(prefix: str, key: str) -> Path:
        return cache_dir / f"{prefix}_{key}.json"

    def _load_cached_list(prefix: str, key: str) -> Optional[List[Dict[str, Any]]]:
        file_path = _cache_file(prefix, key)
        if not file_path.exists():
            return None
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return None

    def _save_cache_json(prefix: str, key: str, payload: Any) -> None:
        file_path = _cache_file(prefix, key)
        tmp_path = file_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(file_path)

    sheet_concurrency = _read_int_env("SHEET_AGENT_CONCURRENCY", 8, low=1, high=32)
    pair_concurrency = _read_int_env("PAIR_AGENT_CONCURRENCY", 16, low=1, high=64)
    prompt_version = os.getenv("DIMENSION_PROMPT_VERSION", "dim_v2_5img_v1")
    logger.info(
        "dimension_audit start project=%s version=%s sheet_concurrency=%s pair_concurrency=%s",
        project_id,
        audit_version,
        sheet_concurrency,
        pair_concurrency,
    )

    json_rows = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .all()
    )
    drawing_rows = (
        db.query(Drawing)
        .filter(
            Drawing.project_id == project_id,
            Drawing.replaced_at == None,
        )
        .all()
    )

    json_by_sheet: Dict[str, Dict[str, Any]] = {}
    for row in json_rows:
        if not row.json_path or not row.sheet_no:
            continue
        try:
            payload = _read_json(row.json_path)
        except Exception:
            continue
        enriched = enrich_json_with_coordinates(payload)
        key = _norm_sheet_no(row.sheet_no)
        if not key:
            continue
        json_by_sheet[key] = {
            "row": row,
            "sheet_no": row.sheet_no,
            "sheet_name": payload.get("sheet_name") or payload.get("layout_name") or "",
            "dimensions": enriched.get("dimensions", []) or [],
            "indexes": enriched.get("indexes", []) or [],
            "model_range": enriched.get("model_range") or {},
        }

    page_assets_by_sheet = _collect_page_asset_map(drawing_rows)

    pair_keys = set()
    pairs: List[Dict[str, str]] = []

    if pair_filters is not None:
        requested_pairs = {
            tuple(sorted([_norm_sheet_no(a), _norm_sheet_no(b)]))
            for a, b in pair_filters
            if _norm_sheet_no(a) and _norm_sheet_no(b) and _norm_sheet_no(a) != _norm_sheet_no(b)
        }
        for a_key, b_key in sorted(requested_pairs):
            if a_key not in json_by_sheet or b_key not in json_by_sheet:
                continue
            pair_key = tuple(sorted([a_key, b_key]))
            if pair_key in pair_keys:
                continue
            pair_keys.add(pair_key)
            pairs.append({"a": a_key, "b": b_key})
    else:
        for src_key, src in json_by_sheet.items():
            for idx in src["indexes"]:
                target_raw = str(idx.get("target_sheet", "") or "").strip()
                tgt_key = _norm_sheet_no(target_raw)
                if not tgt_key or tgt_key not in json_by_sheet or tgt_key == src_key:
                    continue
                pair_key = tuple(sorted([src_key, tgt_key]))
                if pair_key in pair_keys:
                    continue
                pair_keys.add(pair_key)
                pairs.append({"a": src_key, "b": tgt_key})

    if not pairs:
        if pair_filters is not None:
            return []
        raise RuntimeError("未发现可用于尺寸核对的索引图对，无法执行尺寸审核。")

    issues: List[AuditResult] = []
    semantic_cache: Dict[str, List[Dict[str, Any]]] = {}
    semantic_hashes: Dict[str, str] = {}
    sheet_jobs: List[Dict[str, Any]] = []

    involved = {p["a"] for p in pairs} | {p["b"] for p in pairs}
    sheet_cache_hit = 0
    sheet_cache_miss = 0

    for sheet_key in sorted(involved):
        sheet = json_by_sheet[sheet_key]
        dims = sheet["dimensions"]
        if not dims:
            semantic_cache[sheet_key] = []
            semantic_hashes[sheet_key] = _sha256_parts([sheet_key, "empty"])
            continue

        for dim in dims:
            if dim.get("global_pct") is None:
                point = _dimension_global_point(dim, sheet["model_range"])
                if point:
                    dim["global_pct"] = point

        dimension_lookup: Dict[str, Dict[str, Any]] = {}
        for dim in dims:
            dim_id = str(dim.get("id") or "").strip()
            if not dim_id:
                continue
            dim_key = _norm_index_no(dim_id)
            if dim_key and dim_key not in dimension_lookup:
                dimension_lookup[dim_key] = dim
        sheet["dimension_lookup"] = dimension_lookup

        page_asset = page_assets_by_sheet.get(sheet_key)
        if not page_asset:
            raise RuntimeError(f"尺寸核对缺少图纸资产：{sheet['sheet_no']} 未找到对应图像/页码。")
        pdf_path = page_asset.get("pdf_path")
        page_index = page_asset.get("page_index")
        if not pdf_path or page_index is None:
            raise RuntimeError(
                f"尺寸核对缺少PDF页定位：{sheet['sheet_no']} pdf_path={pdf_path} page_index={page_index}"
            )

        dims_compact = _compact_dimensions(dims)
        prompt = _build_single_sheet_prompt(
            sheet_no=sheet["sheet_no"],
            sheet_name=sheet["sheet_name"],
            dims_compact=dims_compact,
        )
        sheet_cache_key = _sha256_parts(
            [
                prompt_version,
                "sheet_semantic",
                sheet_key,
                sheet["sheet_no"] or "",
                str(page_index),
                _file_sig(str(pdf_path)),
                _canonical_json(dims_compact),
            ]
        )

        cached_semantic = _load_cached_list("sheet", sheet_cache_key)
        if cached_semantic is not None:
            semantic_cache[sheet_key] = cached_semantic
            semantic_hashes[sheet_key] = _sha256_parts([sheet_cache_key, _canonical_json(cached_semantic)])
            sheet_cache_hit += 1
            continue

        sheet_jobs.append(
            {
                "sheet_key": sheet_key,
                "sheet_no": sheet["sheet_no"],
                "pdf_path": str(pdf_path),
                "page_index": int(page_index),
                "prompt": prompt,
                "cache_key": sheet_cache_key,
            }
        )
        sheet_cache_miss += 1

    async def _run_sheet_job(job: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], str]:
        images = await asyncio.to_thread(
            _pdf_page_to_5images,
            job["pdf_path"],
            job["page_index"],
            0.20,
        )
        semantic_result = await call_kimi(
            system_prompt=(
                "你是专业施工图审核专家，擅长结合全图与象限图做尺寸语义解析。"
                "只返回JSON数组，不要解释。"
            ),
            user_prompt=job["prompt"],
            images=[
                images["full"],
                images["top_left"],
                images["top_right"],
                images["bottom_left"],
                images["bottom_right"],
            ],
            temperature=0.0,
        )
        if not isinstance(semantic_result, list):
            raise RuntimeError(
                f"尺寸语义分析返回格式异常：{job['sheet_no']}，返回类型={type(semantic_result).__name__}"
            )
        cleaned = [item for item in semantic_result if isinstance(item, dict)]
        await asyncio.to_thread(_save_cache_json, "sheet", job["cache_key"], cleaned)
        return job["sheet_key"], cleaned, job["cache_key"]

    async def _run_sheet_jobs() -> None:
        if not sheet_jobs:
            return
        semaphore = asyncio.Semaphore(sheet_concurrency)

        async def _worker(job: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], str]:
            async with semaphore:
                return await _run_sheet_job(job)

        results = await asyncio.gather(*[_worker(job) for job in sheet_jobs], return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result
            sheet_key, cleaned, cache_key = result
            semantic_cache[sheet_key] = cleaned
            semantic_hashes[sheet_key] = _sha256_parts([cache_key, _canonical_json(cleaned)])

    asyncio.run(_run_sheet_jobs())
    logger.info(
        "dimension_audit sheet_semantic project=%s cache_hit=%s cache_miss=%s involved=%s",
        project_id,
        sheet_cache_hit,
        sheet_cache_miss,
        len(involved),
    )

    pair_cache_hit = 0
    pair_cache_miss = 0
    pair_compare_results: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    pair_jobs: List[Dict[str, Any]] = []

    for pair in pairs:
        a = json_by_sheet[pair["a"]]
        b = json_by_sheet[pair["b"]]
        semantic_a = semantic_cache.get(pair["a"], [])
        semantic_b = semantic_cache.get(pair["b"], [])
        if not semantic_a or not semantic_b:
            continue

        pair_cache_key = _sha256_parts(
            [
                prompt_version,
                "pair_compare",
                pair["a"],
                pair["b"],
                semantic_hashes.get(pair["a"], ""),
                semantic_hashes.get(pair["b"], ""),
            ]
        )
        cached_compare = _load_cached_list("pair", pair_cache_key)
        if cached_compare is not None:
            pair_compare_results[(pair["a"], pair["b"])] = cached_compare
            pair_cache_hit += 1
            continue

        pair_jobs.append(
            {
                "a_key": pair["a"],
                "b_key": pair["b"],
                "a_sheet_no": a["sheet_no"],
                "a_sheet_name": a["sheet_name"],
                "b_sheet_no": b["sheet_no"],
                "b_sheet_name": b["sheet_name"],
                "semantic_a": semantic_a,
                "semantic_b": semantic_b,
                "cache_key": pair_cache_key,
            }
        )
        pair_cache_miss += 1

    async def _run_pair_job(job: Dict[str, Any]) -> Tuple[Tuple[str, str], List[Dict[str, Any]]]:
        compare_result = await call_kimi(
            system_prompt=(
                "你是施工图尺寸一致性审核专家。"
                "你会基于两张图的尺寸语义列表做交叉核对。"
                "只返回JSON数组，不要解释。"
            ),
            user_prompt=_build_pair_compare_prompt(
                a_sheet_no=job["a_sheet_no"],
                a_sheet_name=job["a_sheet_name"],
                a_semantic=job["semantic_a"],
                b_sheet_no=job["b_sheet_no"],
                b_sheet_name=job["b_sheet_name"],
                b_semantic=job["semantic_b"],
            ),
            temperature=0.0,
        )
        if not isinstance(compare_result, list):
            raise RuntimeError(
                f"尺寸图对比对返回格式异常：{job['a_sheet_no']} vs {job['b_sheet_no']}，"
                f"返回类型={type(compare_result).__name__}"
            )
        cleaned = [item for item in compare_result if isinstance(item, dict)]
        await asyncio.to_thread(_save_cache_json, "pair", job["cache_key"], cleaned)
        return (job["a_key"], job["b_key"]), cleaned

    async def _run_pair_jobs() -> None:
        if not pair_jobs:
            return
        semaphore = asyncio.Semaphore(pair_concurrency)

        async def _worker(job: Dict[str, Any]) -> Tuple[Tuple[str, str], List[Dict[str, Any]]]:
            async with semaphore:
                return await _run_pair_job(job)

        results = await asyncio.gather(*[_worker(job) for job in pair_jobs], return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                raise result
            pair_key, payload = result
            pair_compare_results[pair_key] = payload

    asyncio.run(_run_pair_jobs())
    logger.info(
        "dimension_audit pair_compare project=%s cache_hit=%s cache_miss=%s pair_total=%s",
        project_id,
        pair_cache_hit,
        pair_cache_miss,
        len(pair_compare_results),
    )

    for pair in pairs:
        pair_result = pair_compare_results.get((pair["a"], pair["b"]))
        if not pair_result:
            continue
        a = json_by_sheet[pair["a"]]
        b = json_by_sheet[pair["b"]]
        for item in pair_result:
            value_a = item.get("A值", item.get("平面值", item.get("value_a")))
            value_b = item.get("B值", item.get("立面值", item.get("value_b")))
            desc = str(item.get("description") or "").strip()
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            source_grid = str(item.get("source_grid") or evidence.get("source_grid") or "").strip()
            target_grid = str(item.get("target_grid") or evidence.get("target_grid") or "").strip()
            source_dim_id = str(item.get("source_dim_id") or evidence.get("source_dim_id") or "").strip()
            target_dim_id = str(item.get("target_dim_id") or evidence.get("target_dim_id") or "").strip()
            index_hint = str(item.get("index_hint") or evidence.get("index_hint") or "").strip()
            confidence_raw = item.get("confidence", evidence.get("confidence"))
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.0

            loc = str(item.get("位置描述") or item.get("location") or "").strip()
            if not loc and (source_grid or target_grid):
                loc = f"{source_grid or '?'} -> {target_grid or '?'}"

            evidence_parts = []
            if source_grid or target_grid:
                evidence_parts.append(f"网格:{source_grid or '?'}->{target_grid or '?'}")
            if source_dim_id or target_dim_id:
                evidence_parts.append(f"标注ID:{source_dim_id or '?'}->{target_dim_id or '?'}")
            if index_hint:
                evidence_parts.append(f"索引:{index_hint}")
            evidence_parts.append(f"置信度:{confidence:.2f}")
            evidence_text = "；".join(evidence_parts)

            final_desc = desc or (
                f"图纸{a['sheet_no']}与{b['sheet_no']}疑似存在尺寸不一致，A={value_a}, B={value_b}"
            )
            if evidence_text:
                final_desc = f"{final_desc}（{evidence_text}）"

            raw_sheet_no_a = str(item.get("A图号") or item.get("平面图号") or "").strip()
            raw_sheet_no_b = str(item.get("B图号") or item.get("立面图号") or "").strip()
            sheet_no_a = raw_sheet_no_a if _norm_sheet_no(raw_sheet_no_a) in json_by_sheet else a["sheet_no"]
            sheet_no_b = raw_sheet_no_b if _norm_sheet_no(raw_sheet_no_b) in json_by_sheet else b["sheet_no"]

            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="dimension",
                severity="warning",
                sheet_no_a=sheet_no_a,
                sheet_no_b=sheet_no_b,
                location=loc or None,
                value_a=str(value_a) if value_a is not None else None,
                value_b=str(value_b) if value_b is not None else None,
                description=final_desc,
                evidence_json=None,
            )

            anchors: List[Dict[str, Any]] = []
            source_dim_key = _norm_index_no(source_dim_id)
            target_dim_key = _norm_index_no(target_dim_id)
            source_dim = a.get("dimension_lookup", {}).get(source_dim_key) if source_dim_key else None
            target_dim = b.get("dimension_lookup", {}).get(target_dim_key) if target_dim_key else None

            source_anchor = _build_anchor(
                role="source",
                sheet_no=issue.sheet_no_a or a["sheet_no"],
                grid=source_grid or (source_dim or {}).get("grid"),
                global_pct=(source_dim or {}).get("global_pct") if isinstance((source_dim or {}).get("global_pct"), dict) else None,
                confidence=confidence,
                origin="dimension",
            )
            if source_anchor:
                anchors.append(source_anchor)

            target_anchor = _build_anchor(
                role="target",
                sheet_no=issue.sheet_no_b or b["sheet_no"],
                grid=target_grid or (target_dim or {}).get("grid"),
                global_pct=(target_dim or {}).get("global_pct") if isinstance((target_dim or {}).get("global_pct"), dict) else None,
                confidence=confidence,
                origin="dimension",
            )
            if target_anchor:
                anchors.append(target_anchor)

            issue.evidence_json = _to_evidence_json(
                anchors,
                pair_id=f"{pair['a']}::{pair['b']}",
                unlocated_reason=None if anchors else "dimension_pair_unlocated",
            )
            db.add(issue)
            issues.append(issue)

    db.commit()
    logger.info(
        "dimension_audit done project=%s version=%s issues=%s",
        project_id,
        audit_version,
        len(issues),
    )
    return issues


def audit_materials(
    project_id: str,
    audit_version: int,
    db,
    sheet_filters: Optional[List[str]] = None,
) -> List[AuditResult]:
    """
    材料核对：检测未定义/未使用的材料
    
    Args:
        project_id: 项目ID
        audit_version: 审核版本号
        db: 数据库会话
    
    Returns:
        审核结果列表
    """
    allowed_sheet_keys: Optional[set[str]] = None
    if sheet_filters:
        allowed_sheet_keys = {
            _norm_sheet_no(item)
            for item in sheet_filters
            if _norm_sheet_no(item)
        }
        if not allowed_sheet_keys:
            return []

    json_list = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1
        )
        .all()
    )

    issues: List[AuditResult] = []

    def norm_code(value: Optional[str]) -> str:
        if not value:
            return ""
        s = str(value).strip().upper()
        s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", s)
        return s

    def norm_name(value: Optional[str]) -> str:
        if not value:
            return ""
        s = str(value).strip()
        s = re.sub(r"\s+", "", s)
        return s

    def is_valid_material_code(code_key: str) -> bool:
        # 过滤明显噪声：超长串/无数字/非常规编号形式
        if not code_key:
            return False
        if len(code_key) > 12:
            return False
        if not any(ch.isalpha() for ch in code_key):
            return False
        if not any(ch.isdigit() for ch in code_key):
            return False
        return re.match(r"^[A-Z]*\d+[A-Z0-9]*$", code_key) is not None

    for json_data in json_list:
        if allowed_sheet_keys is not None:
            current_key = _norm_sheet_no(json_data.sheet_no)
            if not current_key or current_key not in allowed_sheet_keys:
                continue
        if not json_data.json_path:
            continue

        try:
            with open(json_data.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        data = enrich_json_with_coordinates(data)

        raw_table = data.get("material_table", []) or []
        raw_used = data.get("materials", []) or []

        material_anchor_by_code: Dict[str, Dict[str, Any]] = {}
        for mat in raw_used:
            code_raw = str(mat.get("code", "") or "").strip()
            code_key = norm_code(code_raw)
            if not is_valid_material_code(code_key):
                continue
            if code_key in material_anchor_by_code:
                continue
            anchor = _build_anchor(
                role="single",
                sheet_no=json_data.sheet_no,
                grid=str(mat.get("grid") or "").strip(),
                global_pct=mat.get("global_pct") if isinstance(mat.get("global_pct"), dict) else None,
                confidence=1.0,
                origin="material",
            )
            if anchor:
                material_anchor_by_code[code_key] = anchor

        table_map: Dict[str, Dict[str, str]] = {}
        for item in raw_table:
            code_raw = str(item.get("code", "") or "").strip()
            name_raw = str(item.get("name", "") or "").strip()
            code_key = norm_code(code_raw)
            if not is_valid_material_code(code_key):
                continue
            if code_key not in table_map:
                table_map[code_key] = {"code": code_raw, "name": name_raw}

        used_map: Dict[str, Dict[str, str]] = {}
        for item in raw_used:
            code_raw = str(item.get("code", "") or "").strip()
            name_raw = str(item.get("name", "") or "").strip()
            code_key = norm_code(code_raw)
            if not is_valid_material_code(code_key):
                continue
            if code_key not in used_map:
                used_map[code_key] = {"code": code_raw, "name": name_raw}

        # 1) 使用未定义（error）
        for code_key, used_item in used_map.items():
            if code_key in table_map:
                continue
            anchor = material_anchor_by_code.get(code_key)
            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="material",
                severity="error",
                sheet_no_a=json_data.sheet_no,
                location=f"材料标注{used_item['code']}",
                description=(
                    f"图纸{json_data.sheet_no}中使用了材料编号{used_item['code']}（{used_item['name'] or '未命名'}），"
                    "但材料表中未找到定义。"
                ),
                evidence_json=_to_evidence_json(
                    [anchor] if anchor else [],
                    unlocated_reason=None if anchor else "material_used_without_location",
                ),
            )
            db.add(issue)
            issues.append(issue)

        # 2) 定义未使用（info）
        for code_key, table_item in table_map.items():
            if code_key in used_map:
                continue
            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="material",
                severity="info",
                sheet_no_a=json_data.sheet_no,
                location=f"材料表{table_item['code']}",
                description=(
                    f"材料表中定义了材料编号{table_item['code']}（{table_item['name'] or '未命名'}），"
                    "但在图纸标注中未使用。"
                ),
                evidence_json=_to_evidence_json([], unlocated_reason="material_table_only_no_anchor"),
            )
            db.add(issue)
            issues.append(issue)

        # 3) 同编号名称不一致（warning）
        for code_key, used_item in used_map.items():
            table_item = table_map.get(code_key)
            if not table_item:
                continue
            used_name = norm_name(used_item.get("name"))
            table_name = norm_name(table_item.get("name"))
            if not used_name or not table_name:
                continue
            if used_name == table_name:
                continue
            similarity = SequenceMatcher(None, used_name, table_name).ratio()
            if similarity >= 0.92:
                # 轻微差异（如空格/符号）忽略
                continue
            anchor = material_anchor_by_code.get(code_key)
            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="material",
                severity="warning",
                sheet_no_a=json_data.sheet_no,
                location=f"材料编号{used_item['code']}",
                description=(
                    f"图纸中材料编号{used_item['code']}名称为“{used_item['name'] or '未命名'}”，"
                    f"材料表中同编号名称为“{table_item['name'] or '未命名'}”，请确认是否命名不一致。"
                ),
                evidence_json=_to_evidence_json(
                    [anchor] if anchor else [],
                    unlocated_reason=None if anchor else "material_name_conflict_unlocated",
                ),
            )
            db.add(issue)
            issues.append(issue)

        # 4) 不同编号但名称高度相似（warning）
        # 为避免噪声，仅在同一张图内检查“被使用材料”与“材料表定义”之间高相似且编号不同
        for used_key, used_item in used_map.items():
            used_name = norm_name(used_item.get("name"))
            if len(used_name) < 2:
                continue
            for table_key, table_item in table_map.items():
                if used_key == table_key:
                    continue
                table_name = norm_name(table_item.get("name"))
                if len(table_name) < 2:
                    continue
                ratio = SequenceMatcher(None, used_name, table_name).ratio()
                if ratio < 0.95:
                    continue
                anchor = material_anchor_by_code.get(used_key)
                issue = AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="material",
                    severity="warning",
                    sheet_no_a=json_data.sheet_no,
                    location=f"材料标注{used_item['code']}",
                    description=(
                        f"图纸中材料“{used_item['name'] or '未命名'}”编号为{used_item['code']}，"
                        f"与材料表中“{table_item['name'] or '未命名'}”编号{table_item['code']}高度相似，"
                        "可能存在编号或命名冲突。"
                    ),
                    evidence_json=_to_evidence_json(
                        [anchor] if anchor else [],
                        unlocated_reason=None if anchor else "material_similarity_unlocated",
                    ),
                )
                db.add(issue)
                issues.append(issue)
                break

    db.commit()
    return issues
