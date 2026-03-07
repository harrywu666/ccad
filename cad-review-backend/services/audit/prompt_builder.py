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
                "display_text": item.get("display_text"),
                "layer": item.get("layer"),
                "grid": item.get("grid"),
                "global_pct": {"x": gp.get("x"), "y": gp.get("y")} if gp else None,
                "in_quadrants": item.get("in_quadrants"),
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
