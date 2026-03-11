from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.audit.relationship_discovery",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit.relationship_discovery"):
            sys.modules.pop(name, None)


def _load_modules(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()
    database = importlib.import_module("database")
    models = importlib.import_module("models")
    relationship_discovery = importlib.import_module("services.audit.relationship_discovery")
    database.init_db()
    return database, models, relationship_discovery


def _seed_project(database, models, tmp_path):
    pdf_dir = tmp_path / "pngs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / "sheet.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    for name in ("a101.png", "a401.png"):
        (pdf_dir / name).write_bytes(b"fake-png")

    source_json = tmp_path / "source.json"
    source_json.write_text(
        json.dumps(
            {
                "indexes": [
                    {
                        "index_no": "D1",
                        "target_sheet": "A4.01",
                        "global_pct": {"x": 20, "y": 30},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    target_json = tmp_path / "target.json"
    target_json.write_text(json.dumps({"indexes": []}, ensure_ascii=False), encoding="utf-8")

    db = database.SessionLocal()
    db.add(models.Project(id="proj-rel-findings", name="Relationship Findings"))
    db.add_all(
        [
            models.Catalog(
                id="cat-a101",
                project_id="proj-rel-findings",
                sheet_no="A1.01",
                sheet_name="平面图",
                status="locked",
                sort_order=1,
            ),
            models.Catalog(
                id="cat-a401",
                project_id="proj-rel-findings",
                sheet_no="A4.01",
                sheet_name="节点详图",
                status="locked",
                sort_order=2,
            ),
            models.Drawing(
                id="draw-a101",
                project_id="proj-rel-findings",
                catalog_id="cat-a101",
                sheet_no="A1.01",
                sheet_name="平面图",
                png_path=str(pdf_dir / "a101.png"),
                page_index=0,
                status="matched",
            ),
            models.Drawing(
                id="draw-a401",
                project_id="proj-rel-findings",
                catalog_id="cat-a401",
                sheet_no="A4.01",
                sheet_name="节点详图",
                png_path=str(pdf_dir / "a401.png"),
                page_index=1,
                status="matched",
            ),
            models.JsonData(
                id="json-a101",
                project_id="proj-rel-findings",
                catalog_id="cat-a101",
                sheet_no="A1.01",
                json_path=str(source_json),
                is_latest=1,
            ),
            models.JsonData(
                id="json-a401",
                project_id="proj-rel-findings",
                catalog_id="cat-a401",
                sheet_no="A4.01",
                json_path=str(target_json),
                is_latest=1,
            ),
        ]
    )
    db.commit()
    return db


def test_relationship_worker_v2_attaches_structured_finding(monkeypatch, tmp_path):
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)
    db = _seed_project(database, models, tmp_path)

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            return relationship_discovery.EvidencePack(
                pack_type=request.pack_type,
                images={"source_full": b"source", "target_full": b"target"},
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
                target_pdf_path=request.target_pdf_path,
                target_page_index=request.target_page_index,
            )

    async def fake_call_kimi(**kwargs):
        return [{"source": "A1.01", "target": "A4.01", "relation": "index_ref", "confidence": 0.88}]

    monkeypatch.setattr(relationship_discovery, "get_evidence_service", lambda: _FakeEvidenceService())

    try:
        result = relationship_discovery.asyncio.run(
            relationship_discovery.discover_relationships_v2_async(
                "proj-rel-findings",
                db,
                fake_call_kimi,
            )
        )
    finally:
        db.close()

    assert len(result) == 1
    finding = result[0]["finding"]
    assert finding["source_agent"] == "relationship_review_agent"
    assert finding["review_round"] == 1
    assert finding["status"] == "confirmed"
    assert finding["rule_id"] == "relationship_visual_review"


def test_relationship_worker_v2_marks_needs_review_after_second_low_confidence_round(monkeypatch, tmp_path):
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)
    db = _seed_project(database, models, tmp_path)

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            if request.pack_type.value == "paired_overview_pack":
                images = {"source_full": b"source", "target_full": b"target"}
            else:
                images = {
                    "source_full": b"source",
                    "source_top_left": b"tl",
                    "source_bottom_right": b"br",
                }
            return relationship_discovery.EvidencePack(
                pack_type=request.pack_type,
                images=images,
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
                target_pdf_path=request.target_pdf_path,
                target_page_index=request.target_page_index,
            )

    call_count = {"count": 0}

    async def fake_call_kimi(**kwargs):
        call_count["count"] += 1
        return [{"source": "A1.01", "target": "A4.01", "relation": "index_ref", "confidence": 0.42}]

    monkeypatch.setattr(relationship_discovery, "get_evidence_service", lambda: _FakeEvidenceService())

    try:
        result = relationship_discovery.asyncio.run(
            relationship_discovery.discover_relationships_v2_async(
                "proj-rel-findings",
                db,
                fake_call_kimi,
            )
        )
    finally:
        db.close()

    assert call_count["count"] == 2
    finding = result[0]["finding"]
    assert finding["review_round"] == 3
    assert finding["status"] == "needs_review"
    assert finding["triggered_by"] == "confidence_low"
