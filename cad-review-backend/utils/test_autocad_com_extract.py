#!/usr/bin/env python3
"""
Windows AutoCAD COM extraction smoke test.

Usage:
  python utils/test_autocad_com_extract.py --dwg-dir D:\\dwgs --out-dir D:\\jsons
  python utils/test_autocad_com_extract.py --dwg D:\\a.dwg --dwg D:\\b.dwg --out-dir D:\\jsons
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dwg", action="append", default=[], help="DWG file path, can repeat")
    parser.add_argument("--dwg-dir", default="", help="Directory containing DWG files")
    parser.add_argument("--out-dir", required=True, help="Output directory for layout json files")
    args = parser.parse_args()

    if platform.system() != "Windows":
        print("[WARN] This script is intended for Windows + AutoCAD COM.")

    dwg_paths = [str(Path(p).resolve()) for p in args.dwg]
    if args.dwg_dir:
        dwg_dir = Path(args.dwg_dir).expanduser().resolve()
        if not dwg_dir.exists():
            print(f"[ERROR] dwg-dir not found: {dwg_dir}")
            return 2
        dwg_paths.extend(str(p.resolve()) for p in sorted(dwg_dir.glob("*.dwg")))

    # de-duplicate
    dwg_paths = sorted(set(dwg_paths))
    if not dwg_paths:
        print("[ERROR] no dwg files provided")
        return 3

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    backend_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_dir))
    from services.cad_service import extract_dwg_batch_data  # noqa: WPS433

    result = extract_dwg_batch_data(dwg_paths, str(out_dir))
    summary = {
        "dwg_files": len(dwg_paths),
        "layouts_total": sum(len(v) for v in result.values()),
    }
    print("[INFO] summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    details = {
        Path(k).name: [
            {
                "layout_name": item.get("layout_name", ""),
                "sheet_no": item.get("sheet_no", ""),
                "json_path": item.get("json_path", ""),
            }
            for item in v
        ]
        for k, v in result.items()
    }
    print("[INFO] details:")
    print(json.dumps(details, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
