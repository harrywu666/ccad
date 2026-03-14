from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.audit_runtime.state_transitions",
        "services.audit_runtime_service",
        "services.review_kernel.orchestrator",
        "services.review_kernel.ir_compiler",
        "services.review_kernel.context_slicer",
        "services.review_kernel.rule_engine",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.review_kernel"):
            sys.modules.pop(name, None)


def test_review_kernel_pipeline_persists_results(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    database.init_db()

    json_file = tmp_path / "a101.json"
    json_file.write_text(
        json.dumps(
            {
                "source_dwg": "A1.01 平面图.dwg",
                "layout_name": "A1.01 平面图",
                "sheet_no": "A1.01",
                "sheet_name": "平面布置图",
                "layout_page_range": {"min": [0, 0], "max": [841, 594]},
                "dimensions": [
                    {
                        "id": "DIM-PIPE",
                        "value": 1000,
                        "display_text": "1000",
                        "source": "paper_space",
                        "text_position": [100, 100],
                    }
                ],
                "indexes": [
                    {
                        "id": "IDX-PIPE",
                        "index_no": "01",
                        "target_sheet": "A9.99",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    db = database.SessionLocal()
    try:
        db.add(models.Project(id="proj-kernel", name="Kernel Project", status="auditing"))
        db.add(
            models.JsonData(
                id="json-kernel-1",
                project_id="proj-kernel",
                catalog_id=None,
                sheet_no="A1.01",
                json_path=str(json_file),
                data_version=1,
                is_latest=1,
                summary="test",
                status="matched",
            )
        )
        db.add(
            models.AuditRun(
                id="run-kernel-1",
                project_id="proj-kernel",
                audit_version=1,
                status="running",
                current_step="等待审图内核启动",
                progress=0,
                total_issues=0,
                started_at=datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()

    orchestrator = importlib.import_module("services.review_kernel.orchestrator")
    orchestrator.execute_pipeline("proj-kernel", 1, clear_running=lambda *_: None)

    db = database.SessionLocal()
    try:
        run = (
            db.query(models.AuditRun)
            .filter(models.AuditRun.project_id == "proj-kernel", models.AuditRun.audit_version == 1)
            .first()
        )
        results = (
            db.query(models.AuditResult)
            .filter(models.AuditResult.project_id == "proj-kernel", models.AuditResult.audit_version == 1)
            .all()
        )
    finally:
        db.close()

    assert run is not None
    assert run.status == "done"
    assert run.total_issues >= 1
    assert len(results) >= 1
    first = results[0]
    evidence_payload = json.loads(first.evidence_json or "{}")
    anchors = evidence_payload.get("anchors")
    assert first.type == "index"
    assert first.finding_type == "reference_broken"
    assert first.finding_status == "needs_review"
    assert first.location == "A1.01 / 平面布置图 -> A9.99"
    assert isinstance(anchors, list) and anchors
    source_anchor = next((item for item in anchors if item.get("role") == "source"), None)
    assert isinstance(source_anchor, dict)
    assert source_anchor.get("sheet_no") == "A1.01"
    assert isinstance(source_anchor.get("layout_point"), dict) or isinstance(source_anchor.get("global_pct"), dict)
    assert json_file.with_suffix(".ir.json").exists()
    upgraded_payload = json.loads(json_file.read_text(encoding="utf-8"))
    assert upgraded_payload["schema_version"] == "1.2.0"
    assert isinstance(upgraded_payload.get("layer_state_snapshot"), dict)
    assert isinstance(upgraded_payload.get("text_encoding_evidence"), list)
    assert isinstance(upgraded_payload.get("z_range_summary"), dict)
    assert isinstance(upgraded_payload.get("drawing_register_entry"), dict)
