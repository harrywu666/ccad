"""最新版本记录选择器。"""

from __future__ import annotations

from typing import List, Optional

from models import Drawing, JsonData


# 功能说明：从图纸列表中选择最新的图纸记录，优先按版本号、状态、页码排序
def pick_latest_drawing(rows: List[Drawing]) -> Optional[Drawing]:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            row.data_version or 0,
            1 if row.png_path else 0,
            1 if row.status == "matched" else 0,
            -(row.page_index if row.page_index is not None else 10**9),
        ),
    )


# 功能说明：从JSON数据列表中选择最新的记录，按版本号、路径、状态和创建时间排序
def pick_latest_json(rows: List[JsonData]) -> Optional[JsonData]:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            row.data_version or 0,
            1 if row.json_path else 0,
            1 if row.status == "matched" else 0,
            row.created_at.timestamp() if row.created_at else 0,
        ),
    )
