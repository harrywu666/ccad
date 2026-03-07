"""图号/索引号标准化。"""

from __future__ import annotations

import re
from typing import Optional

_CIRCLED_NUM_MAP = str.maketrans(
    {
        "①": "1",
        "②": "2",
        "③": "3",
        "④": "4",
        "⑤": "5",
        "⑥": "6",
        "⑦": "7",
        "⑧": "8",
        "⑨": "9",
        "⑩": "10",
        "⑪": "11",
        "⑫": "12",
        "⑬": "13",
        "⑭": "14",
        "⑮": "15",
        "⑯": "16",
        "⑰": "17",
        "⑱": "18",
        "⑲": "19",
        "⑳": "20",
    }
)

_SPLIT_RE = re.compile(r"[\s\-_./\\()（）【】\[\]{}:：|]+")


# 功能说明：内部标准化函数，将文本转换为大写并去除分隔符和圆圈数字
def _normalize(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value).strip().upper()
    text = text.translate(_CIRCLED_NUM_MAP)
    return _SPLIT_RE.sub("", text)


# 功能说明：标准化图号，去除特殊字符和空格，统一格式
def normalize_sheet_no(value: Optional[str]) -> str:
    return _normalize(value)


# 功能说明：标准化索引号，使用与图号相同的规则进行格式化
def normalize_index_no(value: Optional[str]) -> str:
    return _normalize(value)
