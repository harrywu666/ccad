from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, catalog_rows, drawing_rows):
        self._catalog_rows = catalog_rows
        self._drawing_rows = drawing_rows

    def query(self, model):  # noqa: ANN001
        model_name = getattr(model, "__name__", "")
        if model_name == "Catalog":
            return _FakeQuery(self._catalog_rows)
        if model_name == "Drawing":
            return _FakeQuery(self._drawing_rows)
        raise AssertionError(f"unexpected model query: {model_name}")


def test_generate_marked_report_uses_final_issue_anchor_bbox_when_available(monkeypatch, tmp_path):
    from services import report_service

    project_dir = tmp_path / "proj-report"
    (project_dir / "reports").mkdir(parents=True, exist_ok=True)
    png_path = project_dir / "sheet_a101.png"
    Image.new("RGB", (200, 120), "white").save(png_path)

    monkeypatch.setattr(report_service, "resolve_project_dir", lambda project, ensure=False: project_dir)

    project = SimpleNamespace(id="proj-report", name="报告测试")
    result = SimpleNamespace(
        id="issue-1",
        type="dimension",
        severity="warning",
        sheet_no_a="A1.01",
        sheet_no_b="A2.00",
        location="A1.01 剖面标高 vs A2.00 立面标高",
        description="标高不一致",
        evidence_json=json.dumps(
            {
                "finding": {
                    "anchors": [
                        {
                            "sheet_no": "A1.01",
                            "role": "source",
                            "highlight_region": {
                                "shape": "cloud_rect",
                                "bbox_pct": {
                                    "x": 10.0,
                                    "y": 20.0,
                                    "width": 20.0,
                                    "height": 10.0,
                                },
                            },
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
    )
    catalog_rows = [
        SimpleNamespace(
            id="catalog-a101",
            project_id=project.id,
            sheet_no="A1.01",
            sheet_name="一层平面",
            sort_order=1,
            status="locked",
        )
    ]
    drawing_rows = [
        SimpleNamespace(
            id="drawing-a101",
            project_id=project.id,
            catalog_id="catalog-a101",
            sheet_no="A1.01",
            sheet_name="一层平面",
            png_path=str(png_path),
            page_index=0,
            data_version=1,
            status="matched",
            replaced_at=None,
        )
    ]

    output = report_service.generate_pdf_marked(
        project,
        [result],
        version=3,
        db=_FakeDb(catalog_rows, drawing_rows),
    )

    anchors_payload = json.loads(Path(output["anchors_json_path"]).read_text(encoding="utf-8"))

    assert output["mode"] == "marked"
    assert anchors_payload["located_issue_count"] == 1
    assert anchors_payload["issues"][0]["anchors"][0]["x"] == 20.0
    assert anchors_payload["issues"][0]["anchors"][0]["y"] == 25.0
