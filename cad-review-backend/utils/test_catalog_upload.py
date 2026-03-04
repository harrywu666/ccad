#!/usr/bin/env python3
"""
Catalog upload smoke test.

Usage:
  ./venv/bin/python utils/test_catalog_upload.py --image /abs/path/catalog.png
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Absolute path to catalog image")
    parser.add_argument("--category", default="cat_1", help="Project category id")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        print(f"[ERROR] image not found: {image_path}")
        return 2

    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))
    from main import app  # noqa: WPS433

    client = TestClient(app)

    project_name = f"catalog-test-{int(time.time() * 1000)}"
    create_resp = client.post(
        "/api/projects",
        json={"name": project_name, "category": args.category, "tags": ["catalog-test"]},
    )
    if create_resp.status_code != 200:
        print("[ERROR] create project failed:", create_resp.status_code, create_resp.text)
        return 3

    project_id = create_resp.json()["id"]
    print(f"[INFO] project_id: {project_id}")

    with image_path.open("rb") as f:
        upload_resp = client.post(
            f"/api/projects/{project_id}/catalog/upload",
            files={"file": (image_path.name, f.read(), "image/png")},
        )

    print(f"[INFO] upload status: {upload_resp.status_code}")
    if upload_resp.status_code != 200:
        print(upload_resp.text)
        return 4

    payload = upload_resp.json()
    print("[INFO] upload response:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    list_resp = client.get(f"/api/projects/{project_id}/catalog")
    print(f"[INFO] saved rows: {len(list_resp.json())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
