"""
为 audit_results 表新增 is_resolved / resolved_at 列（幂等）。

用法：
  ./venv/bin/python utils/migrate_add_audit_result_resolution.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import engine


# 功能说明：主函数，执行数据库迁移，添加is_resolved和resolved_at列
def main() -> int:
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(audit_results)")).fetchall()
        cols = {str(row[1]) for row in rows}

        if "is_resolved" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE audit_results ADD COLUMN is_resolved INTEGER DEFAULT 0"
                )
            )
            print("added column: audit_results.is_resolved")
        else:
            print("is_resolved already exists, skip.")

        if "resolved_at" not in cols:
            conn.execute(
                text("ALTER TABLE audit_results ADD COLUMN resolved_at DATETIME")
            )
            print("added column: audit_results.resolved_at")
        else:
            print("resolved_at already exists, skip.")

        conn.execute(
            text("UPDATE audit_results SET is_resolved = 0 WHERE is_resolved IS NULL")
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
