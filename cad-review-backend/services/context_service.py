"""
图纸上下文构建服务
负责生成 L0/L1/L2 上下文，并构建图纸关系边（sheet_edges）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from domain.sheet_normalization import normalize_sheet_no
from models import Catalog, Drawing, JsonData, SheetContext, SheetEdge


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


def _safe_mtime(path: Optional[str]) -> float:
    if not path:
        return 0.0
    try:
        return Path(path).expanduser().stat().st_mtime
    except Exception:
        return 0.0


def _read_json(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _find_pdf_in_png_dir(png_path: Optional[str]) -> Optional[str]:
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


def _extract_stats(payload: Dict[str, Any]) -> Dict[str, int]:
    return {
        "viewports": len(payload.get("viewports") or []),
        "dimensions": len(payload.get("dimensions") or []),
        "pseudo_texts": len(payload.get("pseudo_texts") or []),
        "indexes": len(payload.get("indexes") or []),
        "title_blocks": len(payload.get("title_blocks") or []),
        "materials": len(payload.get("materials") or []),
        "material_table": len(payload.get("material_table") or []),
        "layers": len(payload.get("layers") or []),
    }


def _make_l0(sheet_no: str, sheet_name: str, status: str, stats: Dict[str, int], scale: str) -> str:
    return (
        f"{sheet_no or 'UNKNOWN'} {sheet_name or ''} | "
        f"status={status} | scale={scale or '-'} | "
        f"dims={stats['dimensions']} idx={stats['indexes']} mats={stats['materials']}"
    ).strip()


def _make_l1(
    sheet_no: str,
    sheet_name: str,
    layout_name: str,
    status: str,
    stats: Dict[str, int],
    targets: List[str],
) -> str:
    lines = [
        f"# Sheet Overview: {sheet_no or 'UNKNOWN'} {sheet_name or ''}".strip(),
        "",
        f"- status: {status}",
        f"- layout: {layout_name or '-'}",
        f"- dimensions: {stats['dimensions']}",
        f"- indexes: {stats['indexes']}",
        f"- materials: {stats['materials']}",
        f"- material_table_rows: {stats['material_table']}",
        "",
        "## Index Targets",
    ]
    if targets:
        for t in targets[:20]:
            lines.append(f"- {t}")
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def _semantic_hash(parts: List[str]) -> str:
    digest = hashlib.sha256()
    for item in parts:
        digest.update((item or "").encode("utf-8", errors="ignore"))
        digest.update(b"\n")
    return digest.hexdigest()


def _upsert_context(
    project_id: str,
    catalog_id: Optional[str],
    sheet_no: Optional[str],
    db,
) -> SheetContext:
    if catalog_id:
        row = (
            db.query(SheetContext)
            .filter(
                SheetContext.project_id == project_id,
                SheetContext.catalog_id == catalog_id,
            )
            .first()
        )
    else:
        row = (
            db.query(SheetContext)
            .filter(
                SheetContext.project_id == project_id,
                SheetContext.catalog_id == None,
                SheetContext.sheet_no == sheet_no,
            )
            .first()
        )
    if row:
        return row
    row = SheetContext(
        project_id=project_id,
        catalog_id=catalog_id,
        sheet_no=sheet_no,
    )
    db.add(row)
    db.flush()
    return row


def build_sheet_contexts(project_id: str, db) -> Dict[str, Any]:
    """
    构建项目图纸上下文与关系边。

    Returns:
        {
          "contexts_total": int,
          "ready_contexts": int,
          "edges_total": int
        }
    """
    catalogs = (
        db.query(Catalog)
        .filter(
            Catalog.project_id == project_id,
            Catalog.status == "locked",
        )
        .order_by(Catalog.sort_order.asc())
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
    json_rows = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .all()
    )

    drawing_by_catalog: Dict[str, List[Drawing]] = {}
    for row in drawing_rows:
        if not row.catalog_id:
            continue
        drawing_by_catalog.setdefault(row.catalog_id, []).append(row)

    json_by_catalog: Dict[str, List[JsonData]] = {}
    for row in json_rows:
        if not row.catalog_id:
            continue
        json_by_catalog.setdefault(row.catalog_id, []).append(row)

    active_context_ids: List[str] = []
    ready_payloads: Dict[str, Dict[str, Any]] = {}
    contexts_total = 0
    ready_contexts = 0

    # 目录锁定后，按目录基准构建上下文
    for item in catalogs:
        drawing = _pick_latest_drawing(drawing_by_catalog.get(item.id, []))
        json_data = _pick_latest_json(json_by_catalog.get(item.id, []))

        has_png = bool(drawing and drawing.png_path)
        has_json = bool(json_data and json_data.json_path)
        if has_png and has_json:
            status = "ready"
        elif (not has_png) and has_json:
            status = "missing_png"
        elif has_png and (not has_json):
            status = "missing_json"
        else:
            status = "missing_all"

        payload = _read_json(json_data.json_path if json_data else None)
        stats = _extract_stats(payload)
        indexes = payload.get("indexes") or []
        targets = [
            str(x.get("target_sheet", "")).strip()
            for x in indexes
            if isinstance(x, dict) and str(x.get("target_sheet", "")).strip()
        ]

        sheet_no = (item.sheet_no or "").strip()
        sheet_name = (item.sheet_name or "").strip()
        layout_name = str(payload.get("layout_name", "")).strip()
        scale = str(payload.get("scale", "")).strip()
        pdf_path = _find_pdf_in_png_dir(drawing.png_path if drawing else None)
        page_index = drawing.page_index if drawing else None
        json_path = json_data.json_path if json_data else None

        l0 = _make_l0(sheet_no, sheet_name, status, stats, scale)
        l1 = _make_l1(sheet_no, sheet_name, layout_name, status, stats, targets)
        semantic_hash = _semantic_hash(
            [
                project_id,
                sheet_no,
                sheet_name,
                status,
                str(page_index if page_index is not None else ""),
                str(json_path or ""),
                str(_safe_mtime(json_path)),
                str(drawing.png_path if drawing else ""),
                str(_safe_mtime(drawing.png_path if drawing else "")),
                str(pdf_path or ""),
                scale,
                str(stats),
            ]
        )

        context = _upsert_context(project_id, item.id, sheet_no or None, db)
        context.sheet_no = sheet_no or None
        context.sheet_name = sheet_name or None
        context.status = status
        context.layer_l0 = l0
        context.layer_l1 = l1
        context.layer_l2_json_path = json_path or None
        context.layer_l2_pdf_path = pdf_path or None
        context.layer_l2_page_index = page_index
        context.semantic_hash = semantic_hash
        context.meta_json = json.dumps(
            {
                "layout_name": layout_name,
                "scale": scale,
                "stats": stats,
                "targets": targets,
                "png_path": drawing.png_path if drawing else None,
                "json_path": json_path,
            },
            ensure_ascii=False,
        )
        db.add(context)
        db.flush()

        active_context_ids.append(context.id)
        contexts_total += 1

        key = normalize_sheet_no(sheet_no)
        if status == "ready" and key and payload:
            ready_payloads[key] = {
                "sheet_no": sheet_no,
                "payload": payload,
            }
            ready_contexts += 1

    # 删除本项目旧上下文快照（不在本次构建中）
    if active_context_ids:
        (
            db.query(SheetContext)
            .filter(
                SheetContext.project_id == project_id,
                SheetContext.id.notin_(active_context_ids),
            )
            .delete(synchronize_session=False)
        )
    else:
        db.query(SheetContext).filter(SheetContext.project_id == project_id).delete(synchronize_session=False)

    # 关系边重建（仅清除 index_ref，保留 ai_visual 由后续 AI 发现步骤管理）
    db.query(SheetEdge).filter(
        SheetEdge.project_id == project_id,
        SheetEdge.edge_type == "index_ref",
    ).delete(synchronize_session=False)

    pair_mentions: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for source_key, info in ready_payloads.items():
        payload = info["payload"]
        source_sheet_no = info["sheet_no"]
        for idx in payload.get("indexes") or []:
            if not isinstance(idx, dict):
                continue
            target_raw = str(idx.get("target_sheet", "")).strip()
            target_key = normalize_sheet_no(target_raw)
            if not target_key or target_key == source_key or target_key not in ready_payloads:
                continue

            pair_key = (source_key, target_key)
            pair_mentions.setdefault(pair_key, []).append(
                {
                    "index_no": idx.get("index_no"),
                    "target_sheet_raw": target_raw,
                    "position": idx.get("position"),
                    "global_pct": idx.get("global_pct"),
                    "grid": idx.get("grid"),
                }
            )

    edges_total = 0
    for (src_key, tgt_key), mentions in pair_mentions.items():
        source_sheet_no = ready_payloads[src_key]["sheet_no"]
        target_sheet_no = ready_payloads[tgt_key]["sheet_no"]
        edge = SheetEdge(
            project_id=project_id,
            source_sheet_no=source_sheet_no,
            target_sheet_no=target_sheet_no,
            edge_type="index_ref",
            confidence=1.0,
            evidence_json=json.dumps(
                {
                    "mentions": mentions,
                    "mention_count": len(mentions),
                },
                ensure_ascii=False,
            ),
        )
        db.add(edge)
        edges_total += 1

    db.commit()
    return {
        "contexts_total": contexts_total,
        "ready_contexts": ready_contexts,
        "edges_total": edges_total,
    }

