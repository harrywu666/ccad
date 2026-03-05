"""
将老项目目录从 ~/cad-review/projects/{project_id} 迁移到
{workspace}/projecs/{项目名}，并修正数据库路径字段。

用法：
  ./venv/bin/python utils/migrate_legacy_projects.py
  ./venv/bin/python utils/migrate_legacy_projects.py --project-id proj_xxx
  ./venv/bin/python utils/migrate_legacy_projects.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal  # noqa: E402
from models import Project  # noqa: E402
from services.storage_path_service import migrate_legacy_project  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy project storage paths")
    parser.add_argument("--project-id", default="", help="只迁移一个项目ID")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不执行迁移")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(Project).order_by(Project.updated_at.desc())
        if args.project_id:
            query = query.filter(Project.id == args.project_id)
        projects = query.all()
        if not projects:
            print("No projects found.")
            return 0

        migrated = 0
        skipped = 0
        details = []
        for project in projects:
            result = migrate_legacy_project(project, db, dry_run=args.dry_run)
            details.append(result)
            if result.get("migrated"):
                migrated += 1
            else:
                skipped += 1

        print(json.dumps({"migrated": migrated, "skipped": skipped, "details": details}, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
