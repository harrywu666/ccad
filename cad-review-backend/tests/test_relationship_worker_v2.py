from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.cancel_registry import AuditCancellationRequested


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.audit.relationship_discovery",
        "services.audit_runtime.evidence_planner",
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
    try:
        db.add(models.Project(id="proj-rel-v2", name="Relationship V2"))
        db.add_all(
            [
                models.Catalog(
                    id="cat-a101",
                    project_id="proj-rel-v2",
                    sheet_no="A1.01",
                    sheet_name="平面图",
                    status="locked",
                    sort_order=1,
                ),
                models.Catalog(
                    id="cat-a401",
                    project_id="proj-rel-v2",
                    sheet_no="A4.01",
                    sheet_name="节点详图",
                    status="locked",
                    sort_order=2,
                ),
                models.Drawing(
                    id="draw-a101",
                    project_id="proj-rel-v2",
                    catalog_id="cat-a101",
                    sheet_no="A1.01",
                    sheet_name="平面图",
                    png_path=str(pdf_dir / "a101.png"),
                    page_index=0,
                    status="matched",
                ),
                models.Drawing(
                    id="draw-a401",
                    project_id="proj-rel-v2",
                    catalog_id="cat-a401",
                    sheet_no="A4.01",
                    sheet_name="节点详图",
                    png_path=str(pdf_dir / "a401.png"),
                    page_index=1,
                    status="matched",
                ),
                models.JsonData(
                    id="json-a101",
                    project_id="proj-rel-v2",
                    catalog_id="cat-a101",
                    sheet_no="A1.01",
                    json_path=str(source_json),
                    is_latest=1,
                ),
                models.JsonData(
                    id="json-a401",
                    project_id="proj-rel-v2",
                    catalog_id="cat-a401",
                    sheet_no="A4.01",
                    json_path=str(target_json),
                    is_latest=1,
                ),
            ]
        )
        db.commit()
        return db
    except Exception:
        db.close()
        raise


def test_relationship_worker_v2_prefers_paired_overview_pack(monkeypatch, tmp_path):
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)
    db = _seed_project(database, models, tmp_path)

    captured: dict[str, object] = {}

    class _FakeEvidenceService:
        async def get_evidence_pack(self, request):
            captured["pack_type"] = request.pack_type.value
            return relationship_discovery.EvidencePack(
                pack_type=request.pack_type,
                images={"source_full": b"source", "target_full": b"target"},
                source_pdf_path=request.source_pdf_path,
                source_page_index=request.source_page_index,
                target_pdf_path=request.target_pdf_path,
                target_page_index=request.target_page_index,
            )

    async def fake_call_kimi(**kwargs):
        captured["images_count"] = len(kwargs.get("images") or [])
        return [{"source": "A1.01", "target": "A4.01", "confidence": 0.92}]

    monkeypatch.setattr(relationship_discovery, "get_evidence_service", lambda: _FakeEvidenceService())

    try:
        result = relationship_discovery.asyncio.run(
            relationship_discovery.discover_relationships_v2_async(
                "proj-rel-v2",
                db,
                fake_call_kimi,
            )
        )
    finally:
        db.close()

    assert captured["pack_type"] == "paired_overview_pack"
    assert captured["images_count"] == 2
    assert len(result) == 1
    assert result[0]["source_key"] == "A101"
    assert result[0]["target_key"] == "A401"


def test_relationship_worker_v2_produces_compatible_findings(monkeypatch, tmp_path):
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)
    db = _seed_project(database, models, tmp_path)

    async def fake_call_kimi(**kwargs):
        return [
            {
                "source": "A1.01",
                "target": "A4.01",
                "relation": "index_ref",
                "confidence": 0.88,
            }
        ]

    monkeypatch.setattr(
        relationship_discovery,
        "pdf_page_to_5images",
        lambda *args, **kwargs: {
            "full": b"full",
            "top_left": b"tl",
            "top_right": b"tr",
            "bottom_left": b"bl",
            "bottom_right": b"br",
        },
    )

    try:
        legacy = relationship_discovery.asyncio.run(
            relationship_discovery.discover_relationships_async(
                "proj-rel-v2",
                db,
                fake_call_kimi,
                concurrency=1,
            )
        )
        v2 = relationship_discovery.asyncio.run(
            relationship_discovery.discover_relationships_v2_async(
                "proj-rel-v2",
                db,
                fake_call_kimi,
            )
        )
    finally:
        db.close()

    legacy_pairs = {(item["source_key"], item["target_key"]) for item in legacy}
    v2_pairs = {(item["source_key"], item["target_key"]) for item in v2}
    assert legacy_pairs == v2_pairs == {("A101", "A401")}


def test_relationship_worker_v2_emits_stream_events(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)
    db = _seed_project(database, models, tmp_path)

    captured_events: list[dict[str, object]] = []

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
        raise AssertionError("stream path should be used")

    async def fake_call_kimi_stream(**kwargs):
        await kwargs["on_delta"]("先对照源图，再确认目标图。")
        await kwargs["on_retry"]({"attempt": 2, "reason": "429", "retry_delay_seconds": 1.5})
        return [{"source": "A1.01", "target": "A4.01", "confidence": 0.92}]

    monkeypatch.setattr(relationship_discovery, "get_evidence_service", lambda: _FakeEvidenceService())
    monkeypatch.setattr(relationship_discovery, "call_kimi_stream", fake_call_kimi_stream)
    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda *args, **kwargs: captured_events.append(kwargs),
    )

    try:
        result = relationship_discovery.asyncio.run(
            relationship_discovery.discover_relationships_v2_async(
                "proj-rel-v2",
                db,
                fake_call_kimi,
                audit_version=2,
            )
        )
    finally:
        db.close()

    assert len(result) == 1
    assert any(
        event.get("event_kind") == "provider_stream_delta"
        and event.get("message") == "先对照源图，再确认目标图。"
        for event in captured_events
    )
    assert any(
        event.get("event_kind") == "phase_event"
        and "第 2 次重试" in str(event.get("message") or "")
        for event in captured_events
    )


def test_relationship_discovery_async_propagates_cancel_request(monkeypatch, tmp_path):
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)
    db = _seed_project(database, models, tmp_path)

    async def fake_discover_group(*args, **kwargs):
        raise AuditCancellationRequested("用户手动中断审核")

    monkeypatch.setattr(relationship_discovery, "_discover_group", fake_discover_group)

    try:
        try:
            relationship_discovery.asyncio.run(
                relationship_discovery.discover_relationships_async(
                    "proj-rel-v2",
                    db,
                    lambda **kwargs: [],
                    audit_version=1,
                    concurrency=1,
                )
            )
        except AuditCancellationRequested as exc:
            assert "用户手动中断审核" in str(exc)
        else:
            raise AssertionError("expected AuditCancellationRequested")
    finally:
        db.close()
