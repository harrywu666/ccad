"""Audit 子模块。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "pdf_page_to_5images",
    "build_material_review_prompt",
    "build_pair_compare_prompt",
    "build_single_sheet_prompt",
    "compact_material_rows",
    "compact_dimensions",
    "parse_dimension_pair_item",
    "add_and_commit",
    "audit_indexes",
    "audit_dimensions",
    "audit_materials",
]


def __getattr__(name: str) -> Any:
    if name == "pdf_page_to_5images":
        return import_module(".image_pipeline", __name__).pdf_page_to_5images
    if name in {
        "build_material_review_prompt",
        "build_pair_compare_prompt",
        "build_single_sheet_prompt",
        "compact_material_rows",
        "compact_dimensions",
    }:
        module = import_module(".prompt_builder", __name__)
        return getattr(module, name)
    if name == "parse_dimension_pair_item":
        return import_module(".result_parser", __name__).parse_dimension_pair_item
    if name == "add_and_commit":
        return import_module(".persistence", __name__).add_and_commit
    if name == "audit_indexes":
        return import_module(".index_audit", __name__).audit_indexes
    if name == "audit_dimensions":
        return import_module(".dimension_audit", __name__).audit_dimensions
    if name == "audit_materials":
        return import_module(".material_audit", __name__).audit_materials
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
