"""尺寸审核结果解析。"""

from __future__ import annotations

from typing import Any, Dict


# 功能说明：解析尺寸对比结果项，统一不同格式的字段
def parse_dimension_pair_item(item: Dict[str, Any]) -> Dict[str, Any]:
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

    location = str(item.get("位置描述") or item.get("location") or "").strip()
    if not location and (source_grid or target_grid):
        location = f"{source_grid or '?'} -> {target_grid or '?'}"

    raw_sheet_no_a = str(item.get("A图号") or item.get("平面图号") or "").strip()
    raw_sheet_no_b = str(item.get("B图号") or item.get("立面图号") or "").strip()

    return {
        "value_a": value_a,
        "value_b": value_b,
        "description": desc,
        "evidence": evidence,
        "source_grid": source_grid,
        "target_grid": target_grid,
        "source_dim_id": source_dim_id,
        "target_dim_id": target_dim_id,
        "index_hint": index_hint,
        "confidence": confidence,
        "location": location,
        "raw_sheet_no_a": raw_sheet_no_a,
        "raw_sheet_no_b": raw_sheet_no_b,
    }
