"""Audit helpers shared across index/dimension/material audits."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


# 功能说明：安全地将值转换为浮点数，失败返回None
def safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# 功能说明：构建审计证据的定位锚点信息
def build_anchor(
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
        x = safe_float(global_pct.get("x"))
        y = safe_float(global_pct.get("y"))
        if x is not None and y is not None:
            anchor["global_pct"] = {
                "x": round(max(0.0, min(100.0, x)), 1),
                "y": round(max(0.0, min(100.0, y)), 1),
            }

    if confidence is not None:
        conf = safe_float(confidence)
        if conf is not None:
            anchor["confidence"] = round(max(0.0, min(1.0, conf)), 3)

    if not anchor["sheet_no"]:
        return None
    if "global_pct" not in anchor and not anchor["grid"]:
        return None
    return anchor


# 功能说明：将锚点列表转换为证据JSON字符串
def to_evidence_json(
    anchors: List[Dict[str, Any]],
    *,
    pair_id: Optional[str] = None,
    unlocated_reason: Optional[str] = None,
) -> str:
    payload: Dict[str, Any] = {"anchors": anchors or []}
    if pair_id:
        payload["pair_id"] = pair_id
    if unlocated_reason:
        payload["unlocated_reason"] = unlocated_reason
    return json.dumps(payload, ensure_ascii=False)
