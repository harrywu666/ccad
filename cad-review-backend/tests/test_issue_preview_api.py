from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from datetime import datetime

import fitz
from fastapi.testclient import TestClient
from PIL import Image


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "main",
        "routers.audit",
        "routers.projects",
        "routers.categories",
        "routers.catalog",
        "routers.drawings",
        "routers.dwg",
        "routers.report",
        "routers.settings",
        "routers.feedback",
        "routers.skill_pack",
        "services.audit.issue_preview",
        "services.registration_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers.") or name.startswith("services.audit."):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


def _seed_project(session_local, models) -> None:
    db = session_local()
    try:
        db.add(models.Project(id="proj-preview", name="Preview Project"))
        db.commit()
    finally:
        db.close()


def _create_dummy_png(tmp_path: Path, name: str = "dummy.png") -> str:
    path = tmp_path / name
    Image.new("RGB", (1000, 800), color="white").save(path)
    return str(path)


def _create_pdf_with_index_title(tmp_path: Path, name: str = "dummy.pdf") -> str:
    path = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((760, 430), "3", fontsize=12)
    page.insert_text((780, 430), "MW.01 -5", fontsize=12)
    page.insert_text((755, 448), "A6.02a", fontsize=10)
    page.insert_text((850, 448), "Scale 1:2", fontsize=10)
    doc.save(path)
    doc.close()
    return str(path)


def _seed_source_drawing(session_local, models, *, drawing_id: str, data_version: int, png_path: str) -> None:
    db = session_local()
    try:
        db.add(
            models.Drawing(
                id=drawing_id,
                project_id="proj-preview",
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                png_path=png_path,
                page_index=0,
                data_version=data_version,
                status="matched",
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_issue_result(session_local, models) -> None:
    db = session_local()
    try:
        db.add(
            models.AuditResult(
                id="issue-preview-1",
                project_id="proj-preview",
                audit_version=3,
                type="index",
                severity="error",
                sheet_no_a="A6.00",
                sheet_no_b="A06.00a",
                location="索引3",
                description="图纸A6.00中的索引3 指向 A06.00a，但目录/数据中不存在该目标图。",
                evidence_json=json.dumps(
                    {
                        "anchors": [
                            {
                                "role": "source",
                                "sheet_no": "A6.00",
                                "grid": "F11",
                                "global_pct": {"x": 46.2, "y": 58.4},
                                "origin": "index",
                                "confidence": 1.0,
                            }
                        ],
                        "unlocated_reason": None,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
    finally:
        db.close()


def test_database_initializes_issue_drawing_table(monkeypatch, tmp_path):
    _, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)

    db = session_local()
    try:
        db.add(
            models.AuditIssueDrawing(
                id="match-1",
                project_id="proj-preview",
                audit_result_id="result-1",
                audit_version=1,
                match_side="source",
                drawing_id=None,
                drawing_data_version=None,
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                index_no="3",
                anchor_json=json.dumps({"grid": "F11"}, ensure_ascii=False),
                match_status="missing_drawing",
            )
        )
        db.commit()

        stored = db.query(models.AuditIssueDrawing).filter_by(id="match-1").first()
    finally:
        db.close()

    assert stored is not None
    assert stored.match_side == "source"
    assert stored.sheet_no == "A6.00"


def test_issue_preview_returns_source_drawing_anchor_when_target_drawing_missing(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )
    _seed_issue_result(session_local, models)

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-1/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["issue"]["id"] == "issue-preview-1"
    assert payload["source"]["drawing_id"] == "drawing-a600-v1"
    assert payload["source"]["drawing_data_version"] == 1
    assert payload["source"]["sheet_no"] == "A6.00"
    assert payload["source"]["anchor"]["global_pct"] == {"x": 46.2, "y": 58.4}
    assert payload["source"]["pdf_anchor"]["global_pct"] == {"x": 46.2, "y": 58.4}
    assert payload["source"]["highlight_region"]["shape"] == "cloud_rect"
    assert payload["source"]["highlight_region"]["bbox_pct"]["width"] > 0
    assert payload["source"]["anchor_status"] == "layout_fallback"
    assert payload["target"] is None
    assert payload["missing_reason"] == "missing_target_drawing"


def test_issue_preview_allows_target_drawing_without_anchor(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )

    db = session_local()
    try:
        db.add(
            models.Drawing(
                id="drawing-a601-v1",
                project_id="proj-preview",
                sheet_no="A6.01",
                sheet_name="酒柜详图2",
                png_path=_create_dummy_png(tmp_path, "target-a601-v1.png"),
                page_index=1,
                data_version=1,
                status="matched",
            )
        )
        db.add(
            models.AuditResult(
                id="issue-preview-target-null-anchor",
                project_id="proj-preview",
                audit_version=3,
                type="dimension",
                severity="error",
                sheet_no_a="A6.00",
                sheet_no_b="A6.01",
                location="尺寸100",
                description="目标图存在，但这条问题没有目标锚点。",
                evidence_json=json.dumps(
                    {
                        "anchors": [
                            {
                                "role": "source",
                                "sheet_no": "A6.00",
                                "grid": "F11",
                                "global_pct": {"x": 46.2, "y": 58.4},
                                "origin": "dimension",
                                "confidence": 1.0,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-target-null-anchor-source",
                project_id="proj-preview",
                audit_result_id="issue-preview-target-null-anchor",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-a600-v1",
                drawing_data_version=1,
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                index_no=None,
                anchor_json=json.dumps(
                    {
                        "role": "source",
                        "sheet_no": "A6.00",
                        "grid": "F11",
                        "global_pct": {"x": 46.2, "y": 58.4},
                        "origin": "dimension",
                        "confidence": 1.0,
                    },
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-target-null-anchor-target",
                project_id="proj-preview",
                audit_result_id="issue-preview-target-null-anchor",
                audit_version=3,
                match_side="target",
                drawing_id="drawing-a601-v1",
                drawing_data_version=1,
                sheet_no="A6.01",
                sheet_name="酒柜详图2",
                index_no=None,
                anchor_json=None,
                match_status="missing_anchor",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-target-null-anchor/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"]["drawing_id"] == "drawing-a601-v1"
    assert payload["target"]["anchor"] is None
    assert payload["target"]["layout_anchor"] is None
    assert payload["target"]["pdf_anchor"] is None
    assert payload["target"]["anchor_status"] == "missing"


def test_issue_preview_refreshes_dimension_anchors_from_description_ids(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-g003-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-g003-v1.png"),
    )

    source_json = tmp_path / "g003.json"
    source_json.write_text(
        json.dumps(
            {
                "sheet_no": "G0.03",
                "dimensions": [
                    {"id": "45402", "grid": "B2", "global_pct": {"x": 5.1, "y": 8.0}},
                    {"id": "4557C", "grid": "E2", "global_pct": {"x": 16.7, "y": 8.0}},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    target_json = tmp_path / "g004.json"
    target_json.write_text(
        json.dumps(
            {
                "sheet_no": "G0.04",
                "dimensions": [
                    {"id": "CC3", "grid": "G16", "global_pct": {"x": 25.2, "y": 89.1}},
                    {"id": "FC2", "grid": "R16", "global_pct": {"x": 71.2, "y": 89.1}},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = session_local()
    try:
        source = db.query(models.Drawing).filter_by(id="drawing-g003-v1").first()
        source.sheet_no = "G0.03"
        source.sheet_name = "门表"
        source.page_index = 3
        db.add(
            models.Drawing(
                id="drawing-g004-v1",
                project_id="proj-preview",
                sheet_no="G0.04",
                sheet_name="门详图",
                png_path=_create_dummy_png(tmp_path, "target-g004-v1.png"),
                page_index=4,
                data_version=1,
                status="matched",
            )
        )
        db.add(
            models.JsonData(
                id="json-g003-v1",
                project_id="proj-preview",
                sheet_no="G0.03",
                json_path=str(source_json),
                data_version=1,
                is_latest=1,
            )
        )
        db.add(
            models.JsonData(
                id="json-g004-v1",
                project_id="proj-preview",
                sheet_no="G0.04",
                json_path=str(target_json),
                data_version=1,
                is_latest=1,
            )
        )
        db.add(
            models.AuditResult(
                id="issue-preview-dimension-refresh",
                project_id="proj-preview",
                audit_version=3,
                type="dimension",
                severity="warning",
                sheet_no_a="G0.03",
                sheet_no_b="G0.04",
                location="D-01门边框宽度",
                description="G0.03 与 G0.04 尺寸不一致。网格:B2/E2->G16/R16；标注ID:45402/4557C-CC3/FC2",
                evidence_json=json.dumps(
                    {
                        "anchors": [
                            {"role": "source", "sheet_no": "G0.03", "grid": "B2", "origin": "dimension"},
                            {"role": "target", "sheet_no": "G0.04", "grid": "G16", "origin": "dimension"},
                        ]
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-dimension-refresh-source",
                project_id="proj-preview",
                audit_result_id="issue-preview-dimension-refresh",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-g003-v1",
                drawing_data_version=1,
                sheet_no="G0.03",
                sheet_name="门表",
                index_no=None,
                anchor_json=json.dumps(
                    {"role": "source", "sheet_no": "G0.03", "grid": "B2", "origin": "dimension"},
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-dimension-refresh-target",
                project_id="proj-preview",
                audit_result_id="issue-preview-dimension-refresh",
                audit_version=3,
                match_side="target",
                drawing_id="drawing-g004-v1",
                drawing_data_version=1,
                sheet_no="G0.04",
                sheet_name="门详图",
                index_no=None,
                anchor_json=None,
                match_status="missing_anchor",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-dimension-refresh/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["anchor"]["global_pct"] == {"x": 5.1, "y": 8.0}
    assert payload["source"]["layout_anchor"]["dimension_id"] == "45402"
    assert payload["target"]["anchor"]["global_pct"] == {"x": 25.2, "y": 89.1}
    assert payload["target"]["layout_anchor"]["dimension_id"] == "CC3"
    assert payload["target"]["match_status"] == "matched"
    assert payload["target"]["anchor_status"] == "layout_fallback"


def test_issue_preview_keeps_historical_drawing_binding_after_new_upload(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )
    _seed_issue_result(session_local, models)

    db = session_local()
    try:
        db.add(
            models.AuditIssueDrawing(
                id="match-source-1",
                project_id="proj-preview",
                audit_result_id="issue-preview-1",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-a600-v1",
                drawing_data_version=1,
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                index_no="3",
                anchor_json=json.dumps(
                    {"global_pct": {"x": 46.2, "y": 58.4}, "grid": "F11", "role": "source"},
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.add(
            models.Drawing(
                id="drawing-a600-v2",
                project_id="proj-preview",
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                png_path=_create_dummy_png(tmp_path, "source-a600-v2.png"),
                page_index=1,
                data_version=2,
                status="matched",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-1/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["drawing_id"] == "drawing-a600-v1"
    assert payload["source"]["drawing_data_version"] == 1


def test_issue_preview_prefers_source_drawing_version_from_anchor(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v2",
        data_version=2,
        png_path=_create_dummy_png(tmp_path, "source-a600-v2.png"),
    )

    db = session_local()
    try:
        legacy = db.query(models.Drawing).filter_by(id="drawing-a600-v1").first()
        legacy.replaced_at = datetime.now()
        db.commit()
    finally:
        db.close()

    db = session_local()
    try:
        db.add(
            models.AuditResult(
                id="issue-preview-version-aware",
                project_id="proj-preview",
                audit_version=3,
                type="index",
                severity="error",
                sheet_no_a="A6.00",
                sheet_no_b="A06.00a",
                location="索引3",
                description="图纸A6.00中的索引3 指向 A06.00a，但目录/数据中不存在该目标图。",
                evidence_json=json.dumps(
                    {
                        "anchors": [
                            {
                                "role": "source",
                                "sheet_no": "A6.00",
                                "grid": "F11",
                                "global_pct": {"x": 46.2, "y": 58.4},
                                "origin": "index",
                                "confidence": 1.0,
                                "data_version": 1,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-version-aware/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["drawing_id"] == "drawing-a600-v1"
    assert payload["source"]["drawing_data_version"] == 1


def test_issue_preview_marks_low_confidence_pdf_anchor(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )
    _seed_issue_result(session_local, models)

    db = session_local()
    try:
        db.add(
            models.DrawingLayoutRegistration(
                id="registration-low-confidence",
                project_id="proj-preview",
                drawing_id="drawing-a600-v1",
                drawing_data_version=1,
                sheet_no="A6.00",
                layout_name="A6.00 酒柜详图1",
                pdf_page_index=0,
                layout_page_range_json=json.dumps({"min": [0, 0], "max": [100, 100]}, ensure_ascii=False),
                pdf_page_size_json=json.dumps({"width": 1000, "height": 800}, ensure_ascii=False),
                transform_json=json.dumps({"type": "direct_layout_page"}, ensure_ascii=False),
                registration_method="layout_page_direct",
                registration_confidence=0.4,
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-source-low-confidence",
                project_id="proj-preview",
                audit_result_id="issue-preview-1",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-a600-v1",
                drawing_data_version=1,
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                index_no="3",
                anchor_json=json.dumps(
                    {
                        "role": "source",
                        "sheet_no": "A6.00",
                        "grid": "F11",
                        "origin": "index",
                        "confidence": 1.0,
                        "layout_point": {"x": 46.2, "y": 41.6},
                    },
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-1/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["anchor_status"] == "pdf_low_confidence"
    assert payload["source"]["registration_confidence"] == 0.4
    assert payload["source"]["pdf_anchor"]["confidence"] == 0.35


def test_issue_preview_rebinds_existing_source_record_to_anchor_version(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v2",
        data_version=2,
        png_path=_create_dummy_png(tmp_path, "source-a600-v2.png"),
    )
    db = session_local()
    try:
        legacy = db.query(models.Drawing).filter_by(id="drawing-a600-v1").first()
        legacy.replaced_at = datetime.now()
        db.commit()
    finally:
        db.close()
    _seed_issue_result(session_local, models)

    db = session_local()
    try:
        db.add(
            models.AuditIssueDrawing(
                id="match-source-wrong-version",
                project_id="proj-preview",
                audit_result_id="issue-preview-1",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-a600-v2",
                drawing_data_version=2,
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                index_no="3",
                anchor_json=json.dumps(
                    {
                        "role": "source",
                        "sheet_no": "A6.00",
                        "grid": "F11",
                        "origin": "index",
                        "confidence": 1.0,
                        "global_pct": {"x": 46.2, "y": 58.4},
                        "data_version": 1,
                    },
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-1/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["drawing_id"] == "drawing-a600-v1"
    assert payload["source"]["drawing_data_version"] == 1


def test_issue_preview_downgrades_pdf_anchor_when_local_image_region_is_blank(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )
    _seed_issue_result(session_local, models)

    db = session_local()
    try:
        db.add(
            models.DrawingLayoutRegistration(
                id="registration-direct",
                project_id="proj-preview",
                drawing_id="drawing-a600-v1",
                drawing_data_version=1,
                sheet_no="A6.00",
                layout_name="A6.00 酒柜详图1",
                pdf_page_index=0,
                layout_page_range_json=json.dumps({"min": [0, 0], "max": [100, 100]}, ensure_ascii=False),
                pdf_page_size_json=json.dumps({"width": 1000, "height": 800}, ensure_ascii=False),
                transform_json=json.dumps({"type": "direct_layout_page"}, ensure_ascii=False),
                registration_method="layout_page_direct",
                registration_confidence=1.0,
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-source-direct-blank",
                project_id="proj-preview",
                audit_result_id="issue-preview-1",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-a600-v1",
                drawing_data_version=1,
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                index_no="3",
                anchor_json=json.dumps(
                    {
                        "role": "source",
                        "sheet_no": "A6.00",
                        "grid": "F11",
                        "origin": "index",
                        "confidence": 1.0,
                        "layout_point": {"x": 46.2, "y": 41.6},
                    },
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-1/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["anchor_status"] == "pdf_visual_mismatch"
    assert payload["source"]["pdf_anchor"]["confidence"] == 0.35


def test_issue_preview_uses_pdf_text_fallback_when_dwg_anchor_mismatches(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    png_path = _create_dummy_png(tmp_path, "source-a602a-v1.png")
    _create_pdf_with_index_title(tmp_path, "source-a602a-v1.pdf")
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a602a-v1",
        data_version=1,
        png_path=png_path,
    )

    db = session_local()
    try:
        db.add(
            models.AuditResult(
                id="issue-preview-a602a",
                project_id="proj-preview",
                audit_version=3,
                type="index",
                severity="error",
                sheet_no_a="A6.02a",
                sheet_no_b="A06.02b",
                location="索引3",
                description="图纸A6.02a中的索引3 指向 A06.02b，但目录/数据中不存在该目标图。",
                evidence_json=json.dumps(
                    {
                        "anchors": [
                            {
                                "role": "source",
                                "sheet_no": "A6.02a",
                                "grid": "P9",
                                "global_pct": {"x": 64.1, "y": 51.7},
                                "origin": "index",
                                "confidence": 1.0,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-a602a-source",
                project_id="proj-preview",
                audit_result_id="issue-preview-a602a",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-a602a-v1",
                drawing_data_version=1,
                sheet_no="A6.02a",
                sheet_name="卡座详图2",
                index_no="3",
                anchor_json=json.dumps(
                    {
                        "role": "source",
                        "sheet_no": "A6.02a",
                        "grid": "P9",
                        "global_pct": {"x": 64.1, "y": 51.7},
                        "origin": "index",
                        "confidence": 1.0,
                        "layout_name": "A6.02a 卡座详图2",
                        "layout_point": {"x": 539.182, "y": 286.706},
                    },
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.add(
            models.DrawingLayoutRegistration(
                id="reg-a602a-source",
                project_id="proj-preview",
                drawing_id="drawing-a602a-v1",
                drawing_data_version=1,
                sheet_no="A6.02a",
                layout_name="A6.02a 卡座详图2",
                pdf_page_index=0,
                layout_page_range_json=json.dumps({"min": [0.0, 0.0], "max": [841.0, 594.0]}, ensure_ascii=False),
                pdf_page_size_json=json.dumps({"width": 1000, "height": 800}, ensure_ascii=False),
                transform_json=json.dumps({"type": "layout_page_direct"}, ensure_ascii=False),
                registration_method="layout_page_direct",
                registration_confidence=1.0,
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-a602a/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["anchor_status"] == "pdf_text_fallback"
    assert payload["source"]["pdf_anchor"]["origin"] == "pdf_text"
    assert payload["source"]["pdf_anchor"]["confidence"] == 0.82
    assert payload["source"]["pdf_anchor"]["global_pct"] == {"x": 79.4, "y": 54.3}


def test_issue_preview_refreshes_stale_corner_anchor_from_json(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )
    _seed_issue_result(session_local, models)

    source_json = tmp_path / "source-refresh.json"
    source_json.write_text(
        json.dumps(
            {
                "sheet_no": "A6.00",
                "model_range": {"min": [69267.893, 925.361], "max": [75569.527, 5218.926]},
                "dimensions": [
                    {"text_position": [74987.349, 1187.757], "source": "model_space"},
                    {"text_position": [74252.293, 1187.757], "source": "model_space"},
                ],
                "indexes": [
                    {
                        "index_no": "3",
                        "target_sheet": "A06.00a",
                        "position": [264.329, 450.872],
                        "source": "layout_space",
                        "symbol_bbox": {"min": [246.0, 432.0], "max": [284.0, 470.0]},
                    },
                    {"index_no": "4", "target_sheet": "A6.00a", "position": [444.394, 527.813], "source": "layout_space"},
                ],
                "title_blocks": [
                    {"position": [125.137, 472.989], "sheet_name": "MW.01 -1"},
                    {"position": [125.137, 21.402], "sheet_name": "MW.01 -2"},
                ],
                "viewports": [
                    {"viewport_id": 2, "position": [384.681, 529.846], "width": 630.1633284024895, "height": 94.80825733475251},
                    {"viewport_id": 3, "position": [384.681, 245.65], "width": 630.1633284024895, "height": 429.3564613320139},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = session_local()
    try:
        db.add(
            models.JsonData(
                id="json-refresh-a600",
                project_id="proj-preview",
                sheet_no="A6.00",
                json_path=str(source_json),
                data_version=1,
                is_latest=1,
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-stale-source",
                project_id="proj-preview",
                audit_result_id="issue-preview-1",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-a600-v1",
                drawing_data_version=1,
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                index_no="3",
                anchor_json=json.dumps(
                    {"global_pct": {"x": 0.0, "y": 100.0}, "grid": "A17", "role": "source"},
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-1/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["anchor"]["global_pct"] == {"x": 30.9, "y": 22.7}
    assert payload["source"]["anchor"]["grid"] == "H4"
    assert payload["source"]["highlight_region"]["shape"] == "cloud_rect"
    assert payload["source"]["highlight_region"]["bbox_pct"]["width"] > 0
    assert payload["source"]["highlight_region"]["bbox_pct"]["height"] > 0


def test_issue_preview_does_not_backfill_layout_page_range_implicitly(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=_create_dummy_png(tmp_path, "source-a600-v1.png"),
    )
    _seed_issue_result(session_local, models)

    project_dir = tmp_path / "projects" / "proj-preview"
    json_dir = project_dir / "jsons"
    dwg_dir = project_dir / "dwg"
    json_dir.mkdir(parents=True, exist_ok=True)
    dwg_dir.mkdir(parents=True, exist_ok=True)
    (dwg_dir / "source.dwg").write_text("stub", encoding="utf-8")

    source_json = json_dir / "source-refresh.json"
    source_json.write_text(
        json.dumps(
            {
                "source_dwg": "source.dwg",
                "layout_name": "A6.02 卡座详图1",
                "sheet_no": "A6.00",
                "model_range": {"min": [165630.161, 10778.667], "max": [175487.829, 13896.779]},
                "indexes": [
                    {"index_no": "3", "target_sheet": "A06.00a", "position": [376.937, 325.578], "source": "layout_space"}
                ],
                "title_blocks": [
                    {"position": [67.572, 21.402], "sheet_name": "MW.01 -2"},
                    {"position": [67.572, 346.583], "sheet_name": "MW.01 -1"},
                ],
                "viewports": [
                    {"viewport_id": 2, "position": [372.475, 466.079], "width": 657.177848590359, "height": 207.874165004616},
                    {"viewport_id": 3, "position": [372.475, 180.359], "width": 657.1778485903596, "height": 305.7202772156462},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    layout_json_service = importlib.import_module("services.layout_json_service")
    called = {"count": 0}

    def _fake_backfill(dwg_path, layout_name):
        called["count"] += 1
        return {"min": [0.0, 0.0], "max": [841.0, 594.0]}

    monkeypatch.setattr(layout_json_service, "read_layout_page_range_from_dwg", _fake_backfill)

    db = session_local()
    try:
        db.add(
            models.JsonData(
                id="json-refresh-a600-layout-range",
                project_id="proj-preview",
                sheet_no="A6.00",
                json_path=str(source_json),
                data_version=1,
                is_latest=1,
            )
        )
        db.add(
            models.AuditIssueDrawing(
                id="match-refresh-source",
                project_id="proj-preview",
                audit_result_id="issue-preview-1",
                audit_version=3,
                match_side="source",
                drawing_id="drawing-a600-v1",
                drawing_data_version=1,
                sheet_no="A6.00",
                sheet_name="酒柜详图",
                index_no="3",
                anchor_json=json.dumps(
                    {"global_pct": {"x": 50.7, "y": 44.6}, "grid": "M8", "role": "source"},
                    ensure_ascii=False,
                ),
                match_status="matched",
            )
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.get("/api/projects/proj-preview/audit/results/issue-preview-1/preview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["anchor"]["global_pct"] == {"x": 50.7, "y": 44.6}
    assert payload["source"]["anchor"]["grid"] == "M8"
    assert called["count"] == 0

    refreshed_json = json.loads(source_json.read_text(encoding="utf-8"))
    assert "layout_page_range" not in refreshed_json


def test_batch_issue_preview_keeps_multiple_cloud_regions(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project(session_local, models)
    png_path = _create_dummy_png(tmp_path, "source-a600-v1.png")
    _seed_source_drawing(
        session_local,
        models,
        drawing_id="drawing-a600-v1",
        data_version=1,
        png_path=png_path,
    )

    db = session_local()
    try:
        db.add_all(
            [
                models.AuditResult(
                    id="issue-preview-group-1",
                    project_id="proj-preview",
                    audit_version=3,
                    type="index",
                    severity="error",
                    sheet_no_a="A6.00",
                    location="索引3",
                    description="索引3断链",
                    evidence_json=json.dumps(
                        {
                            "anchors": [
                                {
                                    "role": "source",
                                    "sheet_no": "A6.00",
                                    "global_pct": {"x": 26.2, "y": 38.4},
                                    "origin": "index",
                                    "confidence": 1.0,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                ),
                models.AuditResult(
                    id="issue-preview-group-2",
                    project_id="proj-preview",
                    audit_version=3,
                    type="index",
                    severity="error",
                    sheet_no_a="A6.00",
                    location="索引4",
                    description="索引4断链",
                    evidence_json=json.dumps(
                        {
                            "anchors": [
                                {
                                    "role": "source",
                                    "sheet_no": "A6.00",
                                    "global_pct": {"x": 46.2, "y": 58.4},
                                    "origin": "index",
                                    "confidence": 1.0,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.post(
            "/api/projects/proj-preview/audit/results/batch-preview",
            json={"result_ids": ["issue-preview-group-1", "issue-preview-group-2"]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["highlight_region"]["shape"] == "cloud_rect"
    assert len(payload["extra_source_anchors"]) == 1
    assert payload["extra_source_anchors"][0]["highlight_region"]["shape"] == "cloud_rect"
