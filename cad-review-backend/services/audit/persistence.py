"""Audit 结果持久化。"""

from __future__ import annotations

from typing import Iterable


# 功能说明：将多个数据库对象批量添加并提交到数据库
def add_and_commit(db, rows: Iterable[object]) -> None:  # noqa: ANN001
    for row in rows:
        db.add(row)
    db.commit()
