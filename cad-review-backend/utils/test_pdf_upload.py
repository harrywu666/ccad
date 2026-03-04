#!/usr/bin/env python3
"""
PDF upload smoke test.

Usage:
  ./venv/bin/python utils/test_pdf_upload.py --project-id <id> --pdf /abs/path/file.pdf --lock
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True, help="Existing project id")
    parser.add_argument("--pdf", required=True, help="Absolute path to PDF file")
    parser.add_argument("--lock", action="store_true", help="Lock catalog before upload")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"[ERROR] pdf not found: {pdf_path}")
        return 2

    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))
    from main import app  # noqa: WPS433

    client = TestClient(app)

    project_id = args.project_id
    project_resp = client.get(f"/api/projects/{project_id}")
    if project_resp.status_code != 200:
        print("[ERROR] project not found:", project_resp.status_code, project_resp.text)
        return 3

    catalog_resp = client.get(f"/api/projects/{project_id}/catalog")
    if catalog_resp.status_code != 200:
        print("[ERROR] get catalog failed:", catalog_resp.status_code, catalog_resp.text)
        return 4
    catalog_rows = catalog_resp.json()
    locked_rows = [row for row in catalog_rows if row.get("status") == "locked"]
    print(f"[INFO] catalog rows: {len(catalog_rows)}, locked rows: {len(locked_rows)}")

    if args.lock:
        lock_resp = client.post(f"/api/projects/{project_id}/catalog/lock")
        print(f"[INFO] lock status: {lock_resp.status_code}")
        if lock_resp.status_code != 200:
            print(lock_resp.text)
            return 5

    with pdf_path.open("rb") as f:
        upload_resp = client.post(
            f"/api/projects/{project_id}/drawings/upload",
            files={"file": (pdf_path.name, f.read(), "application/pdf")},
        )

    print(f"[INFO] upload status: {upload_resp.status_code}")
    if upload_resp.status_code != 200:
        print(upload_resp.text)
        return 6

    upload_data = upload_resp.json()
    print("[INFO] upload response:")
    print(json.dumps(upload_data, ensure_ascii=False, indent=2))

    drawings_resp = client.get(f"/api/projects/{project_id}/drawings")
    if drawings_resp.status_code != 200:
        print("[WARN] get drawings failed:", drawings_resp.status_code, drawings_resp.text)
        return 0

    drawings = drawings_resp.json()
    matched = [row for row in drawings if row.get("status") == "matched"]
    unmatched = [row for row in drawings if row.get("status") != "matched"]

    print(f"[INFO] drawings total: {len(drawings)}, matched: {len(matched)}, unmatched: {len(unmatched)}")
    if unmatched:
        sample = unmatched[:5]
        print("[INFO] unmatched sample:")
        print(json.dumps(sample, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
