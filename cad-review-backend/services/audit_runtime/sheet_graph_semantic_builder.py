"""图纸关系语义建图层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class SheetGraph:
    sheet_types: Dict[str, str]
    linked_targets: Dict[str, List[str]]
    node_hosts: Dict[str, List[str]]


def _fallback_semantic_result(candidates: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    contexts = candidates.get("contexts") or []
    edges = candidates.get("edges") or []
    sheet_types = {
        str(item.get("sheet_no") or "").strip(): str(item.get("sheet_type_hint") or "unknown").strip() or "unknown"
        for item in contexts
        if str(item.get("sheet_no") or "").strip()
    }
    linked_targets: Dict[str, List[str]] = {}
    for edge in edges:
        source = str(edge.get("source_sheet_no") or "").strip()
        target = str(edge.get("target_sheet_no") or "").strip()
        if not source or not target:
            continue
        linked_targets.setdefault(source, [])
        if target not in linked_targets[source]:
            linked_targets[source].append(target)
    return {
        "sheet_types": sheet_types,
        "linked_targets": linked_targets,
        "node_hosts": {},
    }


def build_sheet_graph_from_candidates(
    *,
    candidates: Dict[str, List[Dict[str, Any]]],
    llm_runner: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> SheetGraph:
    result = llm_runner(candidates) if llm_runner else _fallback_semantic_result(candidates)
    return SheetGraph(
        sheet_types=dict(result.get("sheet_types") or {}),
        linked_targets={key: list(value) for key, value in dict(result.get("linked_targets") or {}).items()},
        node_hosts={key: list(value) for key, value in dict(result.get("node_hosts") or {}).items()},
    )


__all__ = [
    "SheetGraph",
    "build_sheet_graph_from_candidates",
]
