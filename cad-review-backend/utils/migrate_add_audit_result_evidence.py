"""
为 audit_results 表新增 evidence_json 列（幂等）。

用法：
  ./venv/bin/python utils/migrate_add_audit_result_evidence.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import engine


def main() -> int:
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(audit_results)")).fetchall()
        cols = {str(row[1]) for row in rows}
        if "evidence_json" in cols:
            print("evidence_json already exists, skip.")
            return 0
        conn.execute(text("ALTER TABLE audit_results ADD COLUMN evidence_json TEXT"))
    print("added column: audit_results.evidence_json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
