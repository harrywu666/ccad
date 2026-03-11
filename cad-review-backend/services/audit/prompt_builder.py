"""尺寸审核提示词构建。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from services.ai_prompt_service import resolve_stage_prompts


# 功能说明：压缩尺寸标注数据，保留关键字段并限制数量
def compact_dimensions(dims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in dims[:120]:
        gp = (
            item.get("global_pct") if isinstance(item.get("global_pct"), dict) else None
        )
        compact.append(
            {
                "id": item.get("id"),
                "value": item.get("value"),
                "actual_value": item.get("actual_value"),
                "display_text": item.get("display_text"),
                "layer": item.get("layer"),
                "global_pct": {"x": gp.get("x"), "y": gp.get("y")} if gp else None,
                "in_quadrants": item.get("in_quadrants"),
            }
        )
    return compact


def compact_material_rows(rows: List[Dict[str, Any]], *, limit: int = 80) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in rows[:limit]:
        gp = item.get("global_pct") if isinstance(item.get("global_pct"), dict) else None
        compact.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "global_pct": {"x": gp.get("x"), "y": gp.get("y")} if gp else None,
            }
        )
    return compact


# 功能说明：构建单张图纸尺寸语义分析的提示词
def build_single_sheet_prompt(
    sheet_no: str, sheet_name: str, dims_compact: List[Dict[str, Any]]
) -> str:
    prompts = resolve_stage_prompts(
        "dimension_single_sheet",
        {
            "sheet_no": sheet_no,
            "sheet_name": sheet_name,
            "dims_compact_json": json.dumps(dims_compact, ensure_ascii=False),
        },
    )
    return prompts["user_prompt"]


# 功能说明：构建两张图纸尺寸对比的提示词
def build_pair_compare_prompt(
    a_sheet_no: str,
    a_sheet_name: str,
    a_semantic: List[Dict[str, Any]],
    b_sheet_no: str,
    b_sheet_name: str,
    b_semantic: List[Dict[str, Any]],
) -> str:
    prompts = resolve_stage_prompts(
        "dimension_pair_compare",
        {
            "a_sheet_no": a_sheet_no,
            "a_sheet_name": a_sheet_name,
            "a_semantic_json": json.dumps(a_semantic, ensure_ascii=False),
            "b_sheet_no": b_sheet_no,
            "b_sheet_name": b_sheet_name,
            "b_semantic_json": json.dumps(b_semantic, ensure_ascii=False),
        },
    )
    return prompts["user_prompt"]


def build_visual_only_sheet_prompt(
    sheet_no: str, sheet_name: str,
) -> str:
    """Build prompt for pure-visual dimension analysis (no JSON dimension data)."""
    prompts = resolve_stage_prompts(
        "dimension_visual_only",
        {
            "sheet_no": sheet_no,
            "sheet_name": sheet_name,
        },
    )
    return prompts["user_prompt"]


def build_material_review_prompt(
    sheet_no: str,
    material_table: List[Dict[str, Any]],
    material_used: List[Dict[str, Any]],
) -> str:
    prompts = resolve_stage_prompts(
        "material_consistency_review",
        {
            "sheet_no": sheet_no,
            "material_table_json": json.dumps(material_table, ensure_ascii=False),
            "material_used_json": json.dumps(material_used, ensure_ascii=False),
        },
    )
    return prompts["user_prompt"]
