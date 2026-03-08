"""Load layout JSON and optionally backfill legacy fields from source DWG."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from services.coordinate_service import enrich_json_with_coordinates
from services.dxf_service import (
    read_layout_detail_titles_from_dwg,
    read_layout_indexes_from_dwg,
    read_layout_page_range_from_dwg,
    read_layout_structure_from_dwg,
)


def _normalize_range(range_obj: Any) -> Optional[Dict[str, list[float]]]:
    if not isinstance(range_obj, dict):
        return None
    mn = range_obj.get("min")
    mx = range_obj.get("max")
    if not isinstance(mn, list) or not isinstance(mx, list) or len(mn) < 2 or len(mx) < 2:
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


def _locate_source_dwg(raw: Dict[str, Any], json_path: str) -> Optional[Path]:
    source_name = str(raw.get("source_dwg") or "").strip()
    if not source_name:
        return None

    json_file = Path(json_path).expanduser().resolve()
    project_dir = json_file.parent.parent
    candidate = project_dir / "dwg" / source_name
    if candidate.exists():
        return candidate
    return None


def maybe_backfill_layout_page_range(raw: Dict[str, Any], json_path: str) -> Dict[str, Any]:
    dwg_path = _locate_source_dwg(raw, json_path)
    layout_name = str(raw.get("layout_name") or "").strip()
    if not dwg_path or not layout_name:
        return raw

    layout_page_range = read_layout_page_range_from_dwg(str(dwg_path), layout_name)
    if _normalize_range(layout_page_range) is None:
        return raw

    existing = _normalize_range(raw.get("layout_page_range"))
    if existing is not None and existing == layout_page_range:
        return raw

    updated = dict(raw)
    updated["layout_page_range"] = layout_page_range

    try:
        Path(json_path).write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return updated


def maybe_backfill_index_visual_anchors(raw: Dict[str, Any], json_path: str) -> Dict[str, Any]:
    indexes = raw.get("indexes")
    if not isinstance(indexes, list) or not indexes:
        return raw
    if all(
        isinstance(item, dict)
        and item.get("insert_position")
        and item.get("anchor_source")
        and item.get("symbol_bbox")
        for item in indexes
    ):
        return raw

    dwg_path = _locate_source_dwg(raw, json_path)
    layout_name = str(raw.get("layout_name") or "").strip()
    if not dwg_path or not layout_name:
        return raw

    extracted_indexes = read_layout_indexes_from_dwg(str(dwg_path), layout_name)
    if not extracted_indexes:
        return raw

    extracted_by_key = {
        (str(item.get("index_no") or "").strip(), str(item.get("target_sheet") or "").strip()): item
        for item in extracted_indexes
    }

    changed = False
    updated_indexes = []
    for item in indexes:
        if not isinstance(item, dict):
            updated_indexes.append(item)
            continue
        key = (str(item.get("index_no") or "").strip(), str(item.get("target_sheet") or "").strip())
        extracted = extracted_by_key.get(key)
        if not extracted:
            updated_indexes.append(item)
            continue

        updated_item = dict(item)
        if extracted.get("position") and updated_item.get("position") != extracted.get("position"):
            updated_item["position"] = extracted["position"]
            changed = True
        if extracted.get("insert_position") and updated_item.get("insert_position") != extracted.get("insert_position"):
            updated_item["insert_position"] = extracted["insert_position"]
            changed = True
        if extracted.get("anchor_source") and updated_item.get("anchor_source") != extracted.get("anchor_source"):
            updated_item["anchor_source"] = extracted["anchor_source"]
            changed = True
        if extracted.get("symbol_bbox") and updated_item.get("symbol_bbox") != extracted.get("symbol_bbox"):
            updated_item["symbol_bbox"] = extracted["symbol_bbox"]
            changed = True
        updated_indexes.append(updated_item)

    if not changed:
        return raw

    updated = dict(raw)
    updated["indexes"] = updated_indexes
    try:
        Path(json_path).write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return updated


def maybe_backfill_detail_titles(raw: Dict[str, Any], json_path: str) -> Dict[str, Any]:
    detail_titles = raw.get("detail_titles")
    if isinstance(detail_titles, list) and detail_titles:
        return raw

    dwg_path = _locate_source_dwg(raw, json_path)
    layout_name = str(raw.get("layout_name") or "").strip()
    if not dwg_path or not layout_name:
        return raw

    extracted_detail_titles = read_layout_detail_titles_from_dwg(str(dwg_path), layout_name)
    if not extracted_detail_titles:
        return raw

    updated = dict(raw)
    updated["detail_titles"] = extracted_detail_titles
    try:
        Path(json_path).write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return updated


def maybe_backfill_layout_fragments(raw: Dict[str, Any], json_path: str) -> Dict[str, Any]:
    has_frames = isinstance(raw.get("layout_frames"), list) and len(raw.get("layout_frames") or []) > 0
    has_fragments = isinstance(raw.get("layout_fragments"), list) and len(raw.get("layout_fragments") or []) > 0
    if has_frames or has_fragments or raw.get("is_placeholder") is True:
        return raw

    dwg_path = _locate_source_dwg(raw, json_path)
    layout_name = str(raw.get("layout_name") or "").strip()
    if not dwg_path or not layout_name:
        return raw

    structure = read_layout_structure_from_dwg(str(dwg_path), layout_name)
    if not structure:
        return raw

    updated = dict(raw)
    if structure.get("sheet_no") and not str(updated.get("sheet_no") or "").strip():
        updated["sheet_no"] = structure["sheet_no"]
    if structure.get("sheet_name") and not str(updated.get("sheet_name") or "").strip():
        updated["sheet_name"] = structure["sheet_name"]
    updated["layout_frames"] = structure.get("layout_frames") or []
    updated["layout_fragments"] = structure.get("layout_fragments") or []
    updated["is_multi_sheet_layout"] = bool(structure.get("is_multi_sheet_layout"))
    try:
        Path(json_path).write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return updated


def _load_raw_layout_json(json_path: str) -> Optional[Dict[str, Any]]:
    try:
        raw = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def backfill_layout_json(json_path: str) -> Optional[Dict[str, Any]]:
    raw = _load_raw_layout_json(json_path)
    if raw is None:
        return None

    updated = maybe_backfill_layout_page_range(raw, json_path)
    updated = maybe_backfill_index_visual_anchors(updated, json_path)
    updated = maybe_backfill_detail_titles(updated, json_path)
    updated = maybe_backfill_layout_fragments(updated, json_path)

    if updated != raw:
        try:
            Path(json_path).write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return updated


def load_enriched_layout_json(json_path: str, *, allow_backfill: bool = False) -> Optional[Dict[str, Any]]:
    raw = backfill_layout_json(json_path) if allow_backfill else _load_raw_layout_json(json_path)
    if raw is None:
        return None
    return enrich_json_with_coordinates(raw)
