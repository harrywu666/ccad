from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

from PIL import Image


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.registration_service",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.registration_service"):
            sys.modules.pop(name, None)


def _load_test_db(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()
    return database.SessionLocal, models


def test_database_initializes_layout_registration_table(monkeypatch, tmp_path):
    session_local, models = _load_test_db(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-registration", name="Registration Project"))
        db.commit()
        db.add(
            models.DrawingLayoutRegistration(
                id="registration-1",
                project_id="proj-registration",
                drawing_id="drawing-1",
                drawing_data_version=2,
                sheet_no="A6.02",
                layout_name="A6.02 卡座详图1",
                pdf_page_index=41,
                layout_page_range_json=json.dumps({"min": [0, 0], "max": [841, 594]}, ensure_ascii=False),
                pdf_page_size_json=json.dumps({"width": 9934, "height": 7017}, ensure_ascii=False),
                transform_json=json.dumps({"type": "direct_layout_page"}, ensure_ascii=False),
                registration_method="layout_page_direct",
                registration_confidence=1.0,
            )
        )
        db.commit()
        stored = db.query(models.DrawingLayoutRegistration).filter_by(id="registration-1").first()
    finally:
        db.close()

    assert stored is not None
    assert stored.layout_name == "A6.02 卡座详图1"
    assert stored.registration_confidence == 1.0


def test_build_pdf_anchor_marks_low_confidence_registration(monkeypatch, tmp_path):
    _, models = _load_test_db(monkeypatch, tmp_path)
    registration = models.DrawingLayoutRegistration(
        id="registration-low-confidence",
        project_id="proj-registration",
        drawing_id="drawing-1",
        drawing_data_version=2,
        sheet_no="A6.02",
        layout_name="A6.02 卡座详图1",
        pdf_page_index=0,
        layout_page_range_json=json.dumps({"min": [0, 0], "max": [100, 100]}, ensure_ascii=False),
        pdf_page_size_json=json.dumps({"width": 1000, "height": 800}, ensure_ascii=False),
        transform_json=json.dumps({"type": "direct_layout_page"}, ensure_ascii=False),
        registration_method="layout_page_direct",
        registration_confidence=0.45,
    )

    registration_service = importlib.import_module("services.registration_service")
    anchor = registration_service.build_pdf_anchor(
        layout_anchor={
            "role": "source",
            "sheet_no": "A6.02",
            "grid": "K8",
            "origin": "index",
            "confidence": 1.0,
            "layout_point": {"x": 30, "y": 40},
        },
        registration=registration,
    )

    assert anchor is not None
    assert anchor["global_pct"] == {"x": 30.0, "y": 60.0}
    assert anchor["confidence"] == 0.45
    assert anchor["registration_method"] == "layout_page_direct"


def test_ensure_drawing_registration_penalizes_json_version_mismatch(monkeypatch, tmp_path):
    session_local, models = _load_test_db(monkeypatch, tmp_path)
    png_path = tmp_path / "drawing.png"
    Image.new("RGB", (1200, 800), color="white").save(png_path)
    json_path = tmp_path / "sheet.json"
    json_path.write_text(
        json.dumps(
            {
                "layout_name": "A6.02 卡座详图1",
                "layout_page_range": {"min": [0, 0], "max": [841, 594]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = session_local()
    try:
        db.add(models.Project(id="proj-registration", name="Registration Project"))
        db.add(
            models.Drawing(
                id="drawing-v2",
                project_id="proj-registration",
                sheet_no="A6.02",
                sheet_name="卡座详图1",
                png_path=str(png_path),
                page_index=0,
                data_version=2,
                status="matched",
            )
        )
        db.add(
            models.JsonData(
                id="json-v1",
                project_id="proj-registration",
                sheet_no="A6.02",
                json_path=str(json_path),
                data_version=1,
                is_latest=1,
            )
        )
        db.commit()

        registration_service = importlib.import_module("services.registration_service")
        registration = registration_service.ensure_drawing_registration(
            db.query(models.Drawing).filter_by(id="drawing-v2").first(),
            db,
        )
        db.commit()
        method = registration.registration_method if registration is not None else None
        confidence = registration.registration_confidence if registration is not None else None
    finally:
        db.close()

    assert registration is not None
    assert method == "layout_page_version_fallback"
    assert confidence == 0.55
