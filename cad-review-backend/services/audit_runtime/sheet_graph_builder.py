"""图纸关系图构建入口。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from services.audit_runtime.sheet_graph_candidates_builder import build_sheet_graph_candidates
from services.audit_runtime.sheet_graph_semantic_builder import (
    SheetGraph,
    build_sheet_graph_from_candidates,
)


def build_sheet_graph(
    *,
    sheet_contexts: List[Any],
    sheet_edges: List[Any],
    llm_runner: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> SheetGraph:
    candidates = build_sheet_graph_candidates(
        sheet_contexts=sheet_contexts,
        sheet_edges=sheet_edges,
    )
    return build_sheet_graph_from_candidates(
        candidates=candidates,
        llm_runner=llm_runner,
    )


__all__ = [
    "SheetGraph",
    "build_sheet_graph",
]
