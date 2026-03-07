"""
将 workspace 内旧目录 `projecs/*` 迁移到 `projects/*`。

用法：
  ./venv/bin/python utils/migrate_workspace_projects_root.py
  ./venv/bin/python utils/migrate_workspace_projects_root.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.storage_path_service import migrate_workspace_projects_root  # noqa: E402


# 功能说明：主函数，迁移工作空间内错误命名的projecs目录到正确的projects目录
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate workspace projecs/* to projects/*"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不执行迁移")
    args = parser.parse_args()

    result = migrate_workspace_projects_root(dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
