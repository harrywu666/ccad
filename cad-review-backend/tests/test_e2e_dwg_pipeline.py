"""E2E test: run real DWG files through the full extraction pipeline.

Validates the refactored services/dxf/ package produces structurally
correct JSON suitable for downstream AI audit.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

TEST_FILES_ROOT = Path(__file__).resolve().parent.parent.parent / "test-files"

PROJECTS: Dict[str, List[str]] = {
    "test1_cad-红星花园咖啡施工图": [
        "A1.01 平面布置图 FURNITURE.dwg",
        "A2.00~08 立面图 ELEVATIONS.dwg",
        "G0.05 装饰材料表以及装饰材料做法表 Material spec.dwg",
    ],
    "test2_cad-企业展厅施工图": [
        "01 龙焱展厅平面系统图.dwg",
        "02 立面图.dwg",
    ],
    "test3_cad-宁波天誉展厅施工图": [
        "01 宁波天誉展厅平面图.dwg",
        "03 节点.dwg",
    ],
    "test4_cad-乌海样板房B户型施工图": [
        "10PL平面系统图/FF1.00 Plans B平面图.dwg",
        "20EL立面系统图/EL1.00 Elevations 客餐厅立面图.dwg",
        "固定家具/FU.01 入户玄关柜.dwg",
    ],
}

REQUIRED_TOP_KEYS = {
    "source_dwg", "layout_name", "sheet_no", "sheet_name",
    "extracted_at", "data_version", "scale", "model_range",
    "layout_page_range", "layout_frames", "layout_fragments",
    "viewports", "dimensions", "pseudo_texts", "indexes",
    "title_blocks", "detail_titles", "materials", "material_table", "layers",
}


def _collect_dwg_paths() -> List[str]:
    """Resolve all DWG paths, skip any that don't exist on this machine."""
    paths = []
    for project, filenames in PROJECTS.items():
        for filename in filenames:
            full = TEST_FILES_ROOT / project / filename
            if full.exists():
                paths.append(str(full))
    return paths


DWG_PATHS = _collect_dwg_paths()

skip_no_dwg = pytest.mark.skipif(
    not DWG_PATHS,
    reason="No test DWG files found",
)


def _validate_layout_payload(payload: Dict[str, Any], dwg_name: str) -> List[str]:
    """Return a list of validation issues (empty = pass)."""
    issues: List[str] = []

    missing = REQUIRED_TOP_KEYS - set(payload.keys())
    if missing:
        issues.append(f"[{dwg_name}] missing keys: {missing}")

    if payload.get("data_version") != 1:
        issues.append(f"[{dwg_name}] data_version != 1: {payload.get('data_version')}")

    model_range = payload.get("model_range", {})
    if not isinstance(model_range, dict) or "min" not in model_range or "max" not in model_range:
        issues.append(f"[{dwg_name}] invalid model_range")

    page_range = payload.get("layout_page_range", {})
    if isinstance(page_range, dict):
        mn = page_range.get("min", [0, 0])
        mx = page_range.get("max", [0, 0])
        if isinstance(mn, list) and isinstance(mx, list) and len(mn) >= 2 and len(mx) >= 2:
            if mx[0] <= mn[0] and mx[1] <= mn[1]:
                issues.append(f"[{dwg_name}] layout_page_range has zero extent")

    for vp in payload.get("viewports", []):
        if "model_range" not in vp:
            issues.append(f"[{dwg_name}] viewport missing model_range")
            break
        if "frozen_layers" not in vp:
            issues.append(f"[{dwg_name}] viewport missing frozen_layers")
            break

    for dim in payload.get("dimensions", []):
        if "value" not in dim or "text_position" not in dim:
            issues.append(f"[{dwg_name}] dimension missing value or text_position")
            break

    for idx in payload.get("indexes", []):
        if "index_no" not in idx or "position" not in idx:
            issues.append(f"[{dwg_name}] index missing index_no or position")
            break
        if "symbol_bbox" not in idx:
            issues.append(f"[{dwg_name}] index missing symbol_bbox")
            break

    fragments = payload.get("layout_fragments", [])
    if isinstance(fragments, list):
        for frag in fragments:
            if "sheet_no" not in frag or "fragment_bbox" not in frag:
                issues.append(f"[{dwg_name}] fragment missing sheet_no or fragment_bbox")
                break

    layers = payload.get("layers", [])
    if not isinstance(layers, list) or len(layers) == 0:
        issues.append(f"[{dwg_name}] layers is empty")

    return issues


@skip_no_dwg
def test_e2e_process_dwg_files_all_projects():
    """Run process_dwg_files on selected DWGs from all 4 projects."""
    from services.dxf.pipeline import process_dwg_files

    with tempfile.TemporaryDirectory(prefix="ccad-e2e-test-") as out_dir:
        results = process_dwg_files(
            dwg_paths=DWG_PATHS,
            project_id="e2e-test",
            output_dir=out_dir,
        )

        assert len(results) > 0, f"No layouts extracted from {len(DWG_PATHS)} DWGs"

        all_issues: List[str] = []
        json_files_checked = 0

        for record in results:
            assert "dwg_path" in record
            assert "layout_name" in record
            assert "data" in record

            payload = record["data"]
            dwg_name = record.get("dwg", "unknown")
            layout_name = record.get("layout_name", "")

            tag = f"{dwg_name}/{layout_name}"
            issues = _validate_layout_payload(payload, tag)
            all_issues.extend(issues)

            json_path = record.get("json_path", "")
            if json_path and Path(json_path).exists():
                loaded = json.loads(Path(json_path).read_text(encoding="utf-8"))
                assert loaded.get("layout_name") == payload.get("layout_name"), \
                    f"JSON file layout_name mismatch for {tag}"
                json_files_checked += 1

        assert json_files_checked > 0, "No JSON files were written"

    if all_issues:
        report = "\n".join(all_issues)
        pytest.fail(f"Validation issues found:\n{report}")


@skip_no_dwg
def test_e2e_json_usable_for_ai_audit():
    """Verify extracted JSON contains sufficient data for AI audit stages."""
    from services.dxf.pipeline import process_dwg_files

    with tempfile.TemporaryDirectory(prefix="ccad-e2e-audit-") as out_dir:
        results = process_dwg_files(
            dwg_paths=DWG_PATHS,
            project_id="e2e-audit-test",
            output_dir=out_dir,
        )

    layouts_with_dimensions = 0
    layouts_with_indexes = 0
    layouts_with_materials = 0
    layouts_with_viewports = 0
    layouts_with_fragments = 0
    layouts_with_global_pct = 0

    for record in results:
        payload = record["data"]
        if payload.get("dimensions"):
            layouts_with_dimensions += 1
            for dim in payload["dimensions"]:
                if "global_pct" in dim:
                    layouts_with_global_pct += 1
                    break
        if payload.get("indexes"):
            layouts_with_indexes += 1
        if payload.get("materials") or payload.get("material_table"):
            layouts_with_materials += 1
        if payload.get("viewports"):
            layouts_with_viewports += 1
        if payload.get("layout_fragments"):
            layouts_with_fragments += 1

    total = len(results)
    print(f"\n=== E2E Audit Readiness Report ({total} layouts from {len(DWG_PATHS)} DWGs) ===")
    print(f"  Layouts with dimensions:    {layouts_with_dimensions}")
    print(f"  Layouts with indexes:       {layouts_with_indexes}")
    print(f"  Layouts with materials:     {layouts_with_materials}")
    print(f"  Layouts with viewports:     {layouts_with_viewports}")
    print(f"  Layouts with fragments:     {layouts_with_fragments}")
    print(f"  Layouts with global_pct:    {layouts_with_global_pct}")

    assert layouts_with_viewports > 0, "No layouts have viewports — extraction may be broken"
    assert layouts_with_fragments > 0, "No layouts have fragments — fragment detection may be broken"
