#!/usr/bin/env python3
"""Full E2E pipeline test: process ALL DWG files from all 4 test projects.

Outputs JSON to .artifacts/e2e-output/<project>/ and prints a summary report.
Usage: venv/bin/python tests/run_full_e2e.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.dxf.pipeline import process_dwg_files  # noqa: E402

TEST_FILES_ROOT = Path(__file__).resolve().parent.parent.parent / "test-files"
OUTPUT_ROOT = Path(__file__).resolve().parent.parent.parent / ".artifacts" / "e2e-output"

PROJECTS = [
    "test1_cad-红星花园咖啡施工图",
    "test2_cad-企业展厅施工图",
    "test3_cad-宁波天誉展厅施工图",
    "test4_cad-乌海样板房B户型施工图",
]

REQUIRED_TOP_KEYS = {
    "source_dwg", "layout_name", "sheet_no", "sheet_name",
    "extracted_at", "data_version", "scale", "model_range",
    "layout_page_range", "layout_frames", "layout_fragments",
    "viewports", "dimensions", "pseudo_texts", "indexes",
    "title_blocks", "detail_titles", "materials", "material_table", "layers",
}


def collect_dwg_paths(project: str) -> List[str]:
    """Collect all DWG files recursively under a project folder."""
    project_dir = TEST_FILES_ROOT / project
    if not project_dir.exists():
        return []
    return sorted(str(p) for p in project_dir.rglob("*.dwg"))


def validate_payload(payload: Dict[str, Any]) -> List[str]:
    """Return a list of structural issues."""
    issues: List[str] = []
    missing = REQUIRED_TOP_KEYS - set(payload.keys())
    if missing:
        issues.append(f"missing keys: {missing}")
    if payload.get("data_version") != 1:
        issues.append(f"data_version={payload.get('data_version')}")
    mr = payload.get("model_range", {})
    if not isinstance(mr, dict) or "min" not in mr:
        issues.append("invalid model_range")
    return issues


def main() -> None:
    grand_total_dwgs = 0
    grand_total_layouts = 0
    grand_total_issues = 0
    project_reports: List[str] = []

    for project in PROJECTS:
        dwg_paths = collect_dwg_paths(project)
        if not dwg_paths:
            project_reports.append(f"  {project}: SKIPPED (no DWG files found)")
            continue

        out_dir = OUTPUT_ROOT / project
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*70}")
        print(f"Project: {project}")
        print(f"  DWG files: {len(dwg_paths)}")
        print(f"  Output: {out_dir}")
        print(f"{'='*70}")

        t0 = time.time()
        results = process_dwg_files(
            dwg_paths=dwg_paths,
            project_id=f"e2e-{project}",
            output_dir=str(out_dir),
        )
        elapsed = time.time() - t0

        grand_total_dwgs += len(dwg_paths)
        grand_total_layouts += len(results)

        dims_total = 0
        indexes_total = 0
        materials_total = 0
        vp_total = 0
        frag_total = 0
        issue_count = 0

        for record in results:
            payload = record["data"]
            issues = validate_payload(payload)
            if issues:
                tag = f"{record.get('dwg', '?')}/{record.get('layout_name', '?')}"
                print(f"  ISSUE: {tag}: {'; '.join(issues)}")
                issue_count += 1

            if payload.get("dimensions"):
                dims_total += len(payload["dimensions"])
            if payload.get("indexes"):
                indexes_total += len(payload["indexes"])
            if payload.get("materials"):
                materials_total += len(payload["materials"])
            if payload.get("viewports"):
                vp_total += len(payload["viewports"])
            if payload.get("layout_fragments"):
                frag_total += len(payload["layout_fragments"])

        grand_total_issues += issue_count

        report_lines = [
            f"  {project}:",
            f"    DWGs: {len(dwg_paths)}, Layouts: {len(results)}, Time: {elapsed:.1f}s",
            f"    Dimensions: {dims_total}, Indexes: {indexes_total}, "
            f"Materials: {materials_total}, Viewports: {vp_total}, "
            f"Fragments: {frag_total}",
            f"    Issues: {issue_count}",
        ]
        project_reports.extend(report_lines)

        for line in report_lines:
            print(line)

        summary_path = out_dir / "_summary.json"
        summary_data = {
            "project": project,
            "dwg_count": len(dwg_paths),
            "layout_count": len(results),
            "elapsed_seconds": round(elapsed, 1),
            "issue_count": issue_count,
            "stats": {
                "dimensions": dims_total,
                "indexes": indexes_total,
                "materials": materials_total,
                "viewports": vp_total,
                "fragments": frag_total,
            },
            "layouts": [
                {
                    "dwg": r.get("dwg", ""),
                    "layout_name": r.get("layout_name", ""),
                    "sheet_no": r.get("sheet_no", ""),
                    "sheet_name": r.get("sheet_name", ""),
                    "json_path": r.get("json_path", ""),
                    "dims": len(r["data"].get("dimensions", [])),
                    "indexes": len(r["data"].get("indexes", [])),
                    "materials": len(r["data"].get("materials", [])),
                    "viewports": len(r["data"].get("viewports", [])),
                    "fragments": len(r["data"].get("layout_fragments", [])),
                }
                for r in results
            ],
        }
        summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*70}")
    print("GRAND TOTAL")
    print(f"{'='*70}")
    print(f"  DWGs processed:  {grand_total_dwgs}")
    print(f"  Layouts extracted: {grand_total_layouts}")
    print(f"  Total issues:    {grand_total_issues}")
    for line in project_reports:
        print(line)

    if grand_total_issues > 0:
        print(f"\n*** {grand_total_issues} issues detected — review above ***")
        sys.exit(1)
    else:
        print("\nAll layouts passed structural validation.")
        sys.exit(0)


if __name__ == "__main__":
    main()
