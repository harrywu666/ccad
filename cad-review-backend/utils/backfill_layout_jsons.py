from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from database import SessionLocal, init_db
from models import JsonData
from services.layout_json_service import backfill_layout_json


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill legacy layout JSON fields from source DWG.")
    parser.add_argument("--project-id", help="Only backfill one project", default=None)
    parser.add_argument("--latest-only", action="store_true", help="Only process latest JSON rows")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    init_db()

    session = SessionLocal()
    try:
        query = session.query(JsonData).order_by(JsonData.project_id.asc(), JsonData.created_at.asc())
        if args.project_id:
            query = query.filter(JsonData.project_id == args.project_id)
        if args.latest_only:
            query = query.filter(JsonData.is_latest == 1)

        rows = query.all()
        seen_paths: set[str] = set()
        processed = 0
        updated = 0
        missing = 0

        for row in rows:
            json_path = str(row.json_path or "").strip()
            if not json_path or json_path in seen_paths:
                continue
            seen_paths.add(json_path)
            path = Path(json_path).expanduser()
            if not path.exists():
                missing += 1
                continue

            before = path.read_text(encoding="utf-8")
            payload = backfill_layout_json(str(path))
            if payload is None:
                missing += 1
                continue
            after = path.read_text(encoding="utf-8")
            processed += 1
            if after != before:
                updated += 1

        print(
            json.dumps(
                {
                    "project_id": args.project_id,
                    "latest_only": bool(args.latest_only),
                    "processed": processed,
                    "updated": updated,
                    "missing": missing,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
