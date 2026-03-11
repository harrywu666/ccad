"""AutoCAD MTEXT 格式化代码清理工具。

DWG 图纸中的文字（MTEXT/MLEADER/TABLE）包含 AutoCAD 专有的格式化代码，
如 {\\fSimSun|b0|i0|c134|p2;原始地面}、{\\T0.8;A1.04} 等。
此模块将这些格式码剥离，只保留人类可读的纯文本。
"""

from __future__ import annotations

import re

_MTEXT_BRACE_PATTERN = re.compile(r"\{\\[a-zA-Z][^{}]*;([^{}]*)\}")
_MTEXT_STACKING = re.compile(r"\{\\S([^;{}]*);([^{}]*)\}")
_MTEXT_BARE_COMMANDS = re.compile(r"\\[LlOoKkNnAaCcQqWw~]")
_PARAGRAPH_BREAK = re.compile(r"\\[Pp]")
_BACKSLASH_COMMANDS_WITH_VALUE = re.compile(r"\\[HhTtCcQqWw]\d*\.?\d*;?")


def strip_mtext_formatting(text: str) -> str:
    """剥离 AutoCAD MTEXT 格式化代码，返回纯文本。

    Args:
        text: 可能包含 MTEXT 格式码的原始字符串。

    Returns:
        去除格式码后的纯文本。

    Examples:
        >>> strip_mtext_formatting("{\\\\fSimSun|b0|i0|c134|p2;原始地面}")
        '原始地面'
        >>> strip_mtext_formatting("{\\\\T0.8;A1.04}")
        'A1.04'
        >>> strip_mtext_formatting("{\\\\fArial|b0|i0|c0|p34;DOWNLIGHT}")
        'DOWNLIGHT'
    """
    if not text:
        return ""
    s = str(text)

    s = _PARAGRAPH_BREAK.sub(" ", s)

    prev = ""
    while prev != s:
        prev = s
        s = _MTEXT_STACKING.sub(r"\1\2", s)
        s = _MTEXT_BRACE_PATTERN.sub(r"\1", s)

    s = _BACKSLASH_COMMANDS_WITH_VALUE.sub("", s)
    s = _MTEXT_BARE_COMMANDS.sub("", s)
    s = s.replace("{}", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s
