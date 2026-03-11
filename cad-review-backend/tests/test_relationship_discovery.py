from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.ai_prompt_service",
        "services.skill_pack_service",
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


def test_save_ai_edges_clears_stale_rows_when_new_result_is_empty(monkeypatch, tmp_path):
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-rel", name="Relationship Project"))
        db.add(
            models.SheetEdge(
                id="edge-stale",
                project_id="proj-rel",
                source_sheet_no="A1.01",
                target_sheet_no="A4.01",
                edge_type="ai_visual",
                confidence=0.8,
                evidence_json="{}",
            )
        )
        db.commit()

        cleared = relationship_discovery.save_ai_edges("proj-rel", [], db)
        rows = (
            db.query(models.SheetEdge)
            .filter(
                models.SheetEdge.project_id == "proj-rel",
                models.SheetEdge.edge_type == "ai_visual",
            )
            .all()
        )
    finally:
        db.close()

    assert cleared == 0
    assert rows == []


def test_discover_group_uses_configured_stage_user_prompt(monkeypatch, tmp_path):
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)

    captured: dict[str, object] = {}

    async def fake_call_kimi(**kwargs):
        captured["user_prompt"] = kwargs["user_prompt"]
        captured["system_prompt"] = kwargs["system_prompt"]
        captured["images_count"] = len(kwargs.get("images") or [])
        return []

    seen_render_kwargs: dict[str, object] = {}

    def fake_pdf_page_to_5images(pdf_path: str, page_index: int, overlap: float, **kwargs):
        assert pdf_path == "/tmp/a101.pdf"
        assert page_index == 0
        assert overlap == 0.20
        seen_render_kwargs.update(kwargs)
        return {
            "full": b"full",
            "top_left": b"top_left",
            "top_right": b"top_right",
            "bottom_left": b"bottom_left",
            "bottom_right": b"bottom_right",
        }

    db = database.SessionLocal()
    try:
        db.add(
            models.AIPromptSetting(
                stage_key="sheet_relationship_discovery",
                user_prompt_override="自定义关系发现提示词\n{{discovery_prompt}}",
            )
        )
        db.commit()

        monkeypatch.setattr(
            relationship_discovery,
            "pdf_page_to_5images",
            fake_pdf_page_to_5images,
        )

        result = relationship_discovery.asyncio.run(
            relationship_discovery._discover_group(
                [
                    {
                        "sheet_no": "A1.01",
                        "sheet_name": "平面布置图",
                        "pdf_path": "/tmp/a101.pdf",
                        "page_index": 0,
                        "indexes_json": [],
                    }
                ],
                [{"图号": "A1.01", "图名": "平面布置图"}],
                fake_call_kimi,
            )
        )
    finally:
        db.close()

    assert result == []
    assert captured["images_count"] == 5
    assert "自定义关系发现提示词" in str(captured["user_prompt"])
    assert "项目完整目录" in str(captured["user_prompt"])
    assert seen_render_kwargs == {
        "full_dpi": 144.0,
        "detail_dpi": 216.0,
        "max_width": 2800,
    }


def test_build_discovery_prompt_enforces_json_only_contract(monkeypatch, tmp_path):
    _, _, relationship_discovery = _load_modules(monkeypatch, tmp_path)

    prompt = relationship_discovery._build_discovery_prompt(
        [
            {
                "sheet_no": "A1.01",
                "sheet_name": "平面布置图",
                "indexes_json": [],
            }
        ],
        [{"图号": "A1.01", "图名": "平面布置图"}],
    )

    assert "不要输出分析过程" in prompt
    assert "不要输出 ```json" in prompt
    assert "没有关系就只返回[]" in prompt
    assert '"source":"图号"' in prompt
    assert '"target":"目标图号"' in prompt


def test_build_relationship_task_prompt_enforces_json_only_contract(monkeypatch, tmp_path):
    _, _, relationship_discovery = _load_modules(monkeypatch, tmp_path)

    prompt = relationship_discovery._build_relationship_task_prompt(
        {"sheet_no": "A1.01", "sheet_name": "平面图"},
        {"sheet_no": "A4.01", "sheet_name": "节点详图"},
    )

    assert "不要输出分析过程" in prompt
    assert "不要输出 markdown" in prompt
    assert "没有跨图引用关系就只返回[]" in prompt
    assert '"relation":"index_ref|detail_ref|section_ref|elevation_ref|callout_ref"' in prompt
    assert '"index_label":"索引编号或标记文字"' in prompt


def test_group_sheets_honors_configured_group_size(monkeypatch, tmp_path):
    _, _, relationship_discovery = _load_modules(monkeypatch, tmp_path)
    monkeypatch.setenv("AUDIT_RELATIONSHIP_DISCOVERY_GROUP_SIZE", "2")

    groups = relationship_discovery._group_sheets(
        [
            {"sheet_no": "A1.01", "sheet_name": "平面布置图"},
            {"sheet_no": "A1.02", "sheet_name": "平面布置图"},
            {"sheet_no": "A1.03", "sheet_name": "平面布置图"},
            {"sheet_no": "A4.01", "sheet_name": "节点详图"},
        ]
    )

    assert [len(group) for group in groups] == [2, 1, 1]


def test_discover_group_ignores_legacy_business_timeout_env(monkeypatch, tmp_path):
    _, _, relationship_discovery = _load_modules(monkeypatch, tmp_path)

    async def slow_call_kimi(**kwargs):  # noqa: ANN001
        await relationship_discovery.asyncio.sleep(0.05)
        return [{"source": "A1.01", "target": "A4.01"}]

    def fake_pdf_page_to_5images(pdf_path: str, page_index: int, overlap: float, **kwargs):
        return {
            "full": b"full",
            "top_left": b"top_left",
            "top_right": b"top_right",
            "bottom_left": b"bottom_left",
            "bottom_right": b"bottom_right",
        }

    monkeypatch.setenv("AUDIT_RELATIONSHIP_DISCOVERY_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(
        relationship_discovery,
        "pdf_page_to_5images",
        fake_pdf_page_to_5images,
    )

    result = relationship_discovery.asyncio.run(
        relationship_discovery._discover_group(
            [
                {
                    "sheet_no": "A1.01",
                    "sheet_name": "平面布置图",
                    "pdf_path": "/tmp/a101.pdf",
                    "page_index": 0,
                    "indexes_json": [],
                }
            ],
            [{"图号": "A1.01", "图名": "平面布置图"}],
            slow_call_kimi,
        )
    )

    assert result == [{"source": "A1.01", "target": "A4.01"}]


def test_discover_relationships_ignores_legacy_total_timeout_env(monkeypatch, tmp_path):
    _, _, relationship_discovery = _load_modules(monkeypatch, tmp_path)

    async def slow_discover_relationships_async(project_id, db, call_kimi, *, concurrency=3):  # noqa: ANN001
        await relationship_discovery.asyncio.sleep(0.05)
        return [{"source": "A1.01", "target": "A4.01"}]

    monkeypatch.setenv("AUDIT_RELATIONSHIP_DISCOVERY_TOTAL_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(
        relationship_discovery,
        "discover_relationships_async",
        slow_discover_relationships_async,
    )

    result = relationship_discovery.discover_relationships("proj-timeout", db=None)

    assert result == [{"source": "A1.01", "target": "A4.01"}]


def test_load_ready_sheets_uses_png_path_when_drawing_has_no_file_path(monkeypatch, tmp_path):
    database, models, relationship_discovery = _load_modules(monkeypatch, tmp_path)

    pdf_dir = tmp_path / "pngs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / "sheet.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    png_path = pdf_dir / "sheet.png"
    png_path.write_bytes(b"fake-png")
    json_path = tmp_path / "sheet.json"
    json_path.write_text('{"indexes":[]}', encoding="utf-8")

    db = database.SessionLocal()
    try:
        project = models.Project(id="proj-load-sheets", name="Load Sheets")
        catalog = models.Catalog(
            id="cat-1",
            project_id="proj-load-sheets",
            sheet_no="A1.01",
            sheet_name="平面布置图",
            status="locked",
            sort_order=1,
        )
        drawing = models.Drawing(
            id="drawing-1",
            project_id="proj-load-sheets",
            catalog_id="cat-1",
            sheet_no="A1.01",
            sheet_name="平面布置图",
            png_path=str(png_path),
            page_index=2,
            status="matched",
        )
        json_data = models.JsonData(
            id="json-1",
            project_id="proj-load-sheets",
            catalog_id="cat-1",
            sheet_no="A1.01",
            json_path=str(json_path),
            is_latest=1,
        )
        db.add_all([project, catalog, drawing, json_data])
        db.commit()

        sheets = relationship_discovery._load_ready_sheets("proj-load-sheets", db)
    finally:
        db.close()

    assert len(sheets) == 1
    assert sheets[0]["pdf_path"] == str(pdf_path)
    assert sheets[0]["page_index"] == 2
