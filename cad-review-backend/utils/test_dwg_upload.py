#!/usr/bin/env python3
"""
DWG upload smoke test.

Usage:
  ./venv/bin/python utils/test_dwg_upload.py --project-id <id> --dummy-name sample.dwg --mock-layouts "A1.01|平面布置图,A1.02|天花布置图"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True, help="Existing project id")
    parser.add_argument("--dummy-name", default="sample.dwg", help="Uploaded dwg filename")
    parser.add_argument(
        "--mock-layouts",
        default="",
        help="Override CAD_MOCK_LAYOUTS, e.g. 'A1.01|平面布置图,A1.02|天花布置图'",
    )
    args = parser.parse_args()

    if not args.dummy_name.lower().endswith(".dwg"):
        print("[ERROR] --dummy-name must end with .dwg")
        return 2

    if args.mock_layouts.strip():
        os.environ["CAD_MOCK_LAYOUTS"] = args.mock_layouts.strip()

    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))
    from main import app  # noqa: WPS433

    client = TestClient(app)
    project_id = args.project_id

    project_resp = client.get(f"/api/projects/{project_id}")
    if project_resp.status_code != 200:
        print("[ERROR] project not found:", project_resp.status_code, project_resp.text)
        return 3

    payload = b"AC1032 DWG MOCK FILE"
    upload_resp = client.post(
        f"/api/projects/{project_id}/dwg/upload",
        files={"files": (args.dummy_name, payload, "application/acad")},
    )
    print(f"[INFO] upload status: {upload_resp.status_code}")
    if upload_resp.status_code != 200:
        print(upload_resp.text)
        return 4

    body = upload_resp.json()
    print("[INFO] upload response:")
    print(json.dumps(body, ensure_ascii=False, indent=2))

    list_resp = client.get(f"/api/projects/{project_id}/dwg")
    print(f"[INFO] latest json rows: {len(list_resp.json())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
