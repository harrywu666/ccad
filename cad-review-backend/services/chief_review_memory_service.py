"""主审运行记忆服务。"""

from __future__ import annotations

from typing import Any, Dict

from services.audit_runtime.project_memory_store import (
    load_project_memory_record,
    save_project_memory_record,
)


def _normalize_project_memory(
    *,
    project_id: str,
    audit_version: int,
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    source = payload or {}
    return {
        "project_id": project_id,
        "audit_version": audit_version,
        "sheet_graph_version": str(source.get("sheet_graph_version") or ""),
        "sheet_summaries": list(source.get("sheet_summaries") or []),
        "confirmed_links": list(source.get("confirmed_links") or []),
        "active_hypotheses": list(source.get("active_hypotheses") or []),
        "resolved_hypotheses": list(source.get("resolved_hypotheses") or []),
        "false_positive_hints": list(source.get("false_positive_hints") or []),
    }


def save_project_memory(
    db,
    *,
    project_id: str,
    audit_version: int,
    payload: Dict[str, Any],
) -> Dict[str, Any]:  # noqa: ANN001
    normalized = _normalize_project_memory(
        project_id=project_id,
        audit_version=audit_version,
        payload=payload,
    )
    save_project_memory_record(
        db,
        project_id=project_id,
        audit_version=audit_version,
        payload=normalized,
    )
    return normalized


def load_project_memory(
    db,
    *,
    project_id: str,
    audit_version: int,
) -> Dict[str, Any]:  # noqa: ANN001
    payload = load_project_memory_record(
        db,
        project_id=project_id,
        audit_version=audit_version,
    )
    return _normalize_project_memory(
        project_id=project_id,
        audit_version=audit_version,
        payload=payload,
    )


__all__ = [
    "load_project_memory",
    "save_project_memory",
]
