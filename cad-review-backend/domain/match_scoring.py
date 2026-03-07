"""目录匹配评分能力。"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, Optional, Set


# 功能说明：标准化匹配文本，去除空白字符、标点符号，保留字母数字和中文字符
def normalize_match_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = value.strip().lower()
    text = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：]+", "", text)
    return "".join(ch for ch in text if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"))


# 功能说明：计算识别图号与目录图号的匹配分数，返回值0.0-1.0之间
def score_sheet_no(recognized: str, catalog: str) -> float:
    if not recognized or not catalog:
        return 0.0
    if recognized == catalog:
        return 1.0

    recognized_norm = normalize_match_text(recognized)
    catalog_norm = normalize_match_text(catalog)
    if not recognized_norm or not catalog_norm:
        return 0.0
    if recognized_norm == catalog_norm:
        return 0.99
    if recognized_norm in catalog_norm or catalog_norm in recognized_norm:
        return 0.94
    return SequenceMatcher(None, recognized_norm, catalog_norm).ratio() * 0.9


# 功能说明：计算识别图名与目录图名的匹配分数，使用文本相似度算法
def score_sheet_name(recognized: str, catalog: str) -> float:
    if not recognized or not catalog:
        return 0.0
    if recognized == catalog:
        return 1.0

    recognized_norm = normalize_match_text(recognized)
    catalog_norm = normalize_match_text(catalog)
    if not recognized_norm or not catalog_norm:
        return 0.0
    if recognized_norm == catalog_norm:
        return 0.98
    if recognized_norm in catalog_norm or catalog_norm in recognized_norm:
        return 0.92
    return SequenceMatcher(None, recognized_norm, catalog_norm).ratio() * 0.9


# 功能说明：从目录候选列表中选择最佳匹配项，综合考虑图号和图名的匹配分数
def pick_catalog_candidate(
    *,
    recognized_no: str,
    recognized_name: str,
    catalogs: Iterable[Any],
    used_catalog_ids: Set[str],
    layout_name: str = "",
    exact_sheet_no_first: bool = False,
) -> Dict[str, Any]:
    if exact_sheet_no_first and recognized_no:
        for item in catalogs:
            if item.id in used_catalog_ids:
                continue
            if (item.sheet_no or "").strip() == recognized_no.strip():
                return {"item": item, "score": 1.0, "no_score": 1.0, "name_score": 0.0}

    best_item = None
    best_score = 0.0
    best_no_score = 0.0
    best_name_score = 0.0

    for item in catalogs:
        if item.id in used_catalog_ids:
            continue

        no_score = score_sheet_no(recognized_no, item.sheet_no or "")
        name_score = score_sheet_name(recognized_name, item.sheet_name or "")
        if layout_name:
            name_score = max(
                name_score, score_sheet_name(layout_name, item.sheet_name or "")
            )

        if recognized_no:
            score = max(no_score, no_score * 0.85 + name_score * 0.25)
            if no_score < 0.60 and name_score >= 0.85:
                score = max(score, name_score * 0.90)
            if no_score >= 0.90 and name_score >= 0.70:
                score += 0.03
        else:
            score = name_score * 0.95

        if score > best_score:
            best_item = item
            best_score = score
            best_no_score = no_score
            best_name_score = name_score

    threshold = 0.72 if recognized_no else 0.78
    if not best_item or best_score < threshold:
        return {
            "item": None,
            "score": best_score,
            "no_score": best_no_score,
            "name_score": best_name_score,
        }

    return {
        "item": best_item,
        "score": best_score,
        "no_score": best_no_score,
        "name_score": best_name_score,
    }
