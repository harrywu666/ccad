from __future__ import annotations

import io
import json
import sys
import uuid
from pathlib import Path

from fastapi import UploadFile


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_ingest_dwg_upload_initial_version_creates_json_without_history(monkeypatch, tmp_path):
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))

    import database
    import models
    from services.drawing_ingest.dwg_ingest_service import ingest_dwg_upload
    from services.storage_path_service import resolve_project_dir

    database.init_db()
    db = database.SessionLocal()
    try:
        project_id = f"proj-{uuid.uuid4()}"
        project = models.Project(id=project_id, name="Demo", status="matching")
        db.add(project)
        catalog_id = f"catalog-{uuid.uuid4()}"
        db.add(
            models.Catalog(
                id=catalog_id,
                project_id=project.id,
                sheet_no="PL-01",
                sheet_name="平面布置图",
                status="locked",
                sort_order=1,
            )
        )
        db.commit()

        async def run_once():
            upload = UploadFile(filename="demo.dwg", file=io.BytesIO(b"dwg-bytes"))
            return await ingest_dwg_upload(
                project.id,
                project,
                [upload],
                db,
                lambda *_args, **_kwargs: None,
            )

        monkeypatch.setattr(
            "services.cad_service.extract_dwg_batch_data",
            lambda **_kwargs: {
                str((resolve_project_dir(project, ensure=True) / "dwg" / "demo.dwg").resolve()): [
                    {
                        "layout_name": "布局1",
                        "sheet_no": "PL-01",
                        "sheet_name": "平面布置图",
                        "json_path": "",
                        "fragment_id": "frag-1",
                        "is_fragment_unit": True,
                        "viewports": [{"id": "vp-1"}],
                        "dimensions": [{"id": "dim-1"}],
                        "pseudo_texts": [],
                        "indexes": [],
                        "title_blocks": [],
                        "materials": [],
                        "material_table": [],
                        "layers": [{"name": "A"}],
                        "data": {
                            "layout_name": "布局1",
                            "sheet_no": "PL-01",
                            "sheet_name": "平面布置图",
                        },
                    }
                ]
            },
        )

        result = __import__("asyncio").run(run_once())
        db.commit()

        row = db.query(models.JsonData).filter_by(project_id=project.id).one()
        assert result["summary"]["matched"] == 1
        assert row.data_version == 1
        assert row.sheet_no == "PL-01"
        assert row.status == "matched"
        assert row.json_path
        assert Path(row.json_path).exists()
        assert "分图:frag-1" in (row.summary or "")
        payload = json.loads(Path(row.json_path).read_text(encoding="utf-8"))
        assert payload["sheet_no"] == "PL-01"
        assert payload["sheet_name"] == "平面布置图"
    finally:
        db.close()
