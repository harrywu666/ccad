"""Audit 通用能力导出。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "pdf_page_to_5images",
    "build_anchor",
    "to_evidence_json",
    "safe_float",
    "get_issue_preview",
    "ensure_issue_drawing_matches",
]


def __getattr__(name: str) -> Any:
    if name == "pdf_page_to_5images":
        return import_module(".image_pipeline", __name__).pdf_page_to_5images
    if name in {"build_anchor", "to_evidence_json", "safe_float"}:
        module = import_module(".common", __name__)
        return getattr(module, name)
    if name in {"get_issue_preview", "ensure_issue_drawing_matches"}:
        module = import_module(".issue_preview", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
