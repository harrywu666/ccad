"""Runner 输出守门与轻修复。"""

from __future__ import annotations

from typing import Any

from services.ai_service import _parse_json


def guard_output(raw_output: str) -> Any:
    text = (raw_output or "").strip()
    if not text:
        raise ValueError("AI 引擎没有返回可修复的内容")
    return _parse_json(text)


__all__ = ["guard_output"]
