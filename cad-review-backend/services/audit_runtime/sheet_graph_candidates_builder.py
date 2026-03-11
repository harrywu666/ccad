"""图纸关系候选整理层。"""

from __future__ import annotations

from typing import Any, Dict, List


def _infer_sheet_type_hint(sheet_name: str) -> str:
    name = str(sheet_name or "").upper()
    name_cn = str(sheet_name or "")
    if "天花" in name_cn or "CEILING" in name:
        return "ceiling"
    if "立面" in name_cn or "ELEVATION" in name:
        return "elevation"
    if "节点" in name_cn or "DETAIL" in name or "NODE" in name:
        return "detail"
    if "平面" in name_cn or "PLAN" in name:
        return "plan"
    return "unknown"


def build_sheet_graph_candidates(
    *,
    sheet_contexts: List[Any],
    sheet_edges: List[Any],
) -> Dict[str, List[Dict[str, Any]]]:
    contexts: List[Dict[str, Any]] = []
    for item in sheet_contexts:
        contexts.append(
            {
                "sheet_no": str(getattr(item, "sheet_no", "") or "").strip(),
                "sheet_name": str(getattr(item, "sheet_name", "") or "").strip(),
                "sheet_type_hint": _infer_sheet_type_hint(getattr(item, "sheet_name", "")),
            }
        )

    edges: List[Dict[str, Any]] = []
    for item in sheet_edges:
        edges.append(
            {
                "source_sheet_no": str(getattr(item, "source_sheet_no", "") or "").strip(),
                "target_sheet_no": str(getattr(item, "target_sheet_no", "") or "").strip(),
                "edge_type": str(getattr(item, "edge_type", "") or "").strip() or "index_ref",
            }
        )

    return {
        "contexts": contexts,
        "edges": edges,
    }


__all__ = [
    "build_sheet_graph_candidates",
]
