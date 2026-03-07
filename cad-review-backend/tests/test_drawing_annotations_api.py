from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# 功能说明：清除后端模块缓存，确保测试使用干净的数据库状态
def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "main",
        "routers.drawings",
        "routers.projects",
        "routers.catalog",
        "routers.categories",
        "routers.audit",
        "routers.report",
        "routers.settings",
        "routers.dwg",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


# 功能说明：加载测试应用，设置临时数据库路径并初始化数据库
def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()

    return main.app, database.SessionLocal, models


# 功能说明：初始化测试数据，创建项目和图纸记录
def _seed_project_and_drawing(session_local, models):
    db = session_local()
    try:
        project = models.Project(id="proj-1", name="Test Project")
        drawing = models.Drawing(
            id="drawing-1",
            project_id="proj-1",
            sheet_no="A1.01",
            sheet_name="首层平面图",
            png_path=str(BACKEND_DIR / "tests" / "fixtures" / "dummy.png"),
            page_index=0,
            data_version=2,
            status="matched",
        )
        db.add(project)
        db.add(drawing)
        db.commit()
    finally:
        db.close()


# 功能说明：测试当标注不存在时，获取标注接口返回空画板
def test_get_annotations_returns_empty_board_when_none_exists(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_drawing(session_local, models)
    client = TestClient(app)

    response = client.get("/api/projects/proj-1/drawings/drawing-1/annotations")

    assert response.status_code == 200
    assert response.json() == {
        "drawing_id": "drawing-1",
        "drawing_data_version": 2,
        "schema_version": 1,
        "objects": [],
    }


# 功能说明：测试标注的PUT和GET操作往返，验证数据一致性
def test_put_then_get_round_trips_annotation_board(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_drawing(session_local, models)
    client = TestClient(app)

    payload = {
        "drawing_data_version": 2,
        "schema_version": 1,
        "objects": [
            {
                "type": "stroke",
                "color": "#ff3b30",
                "stroke_width": 4,
                "path": "M 10 10 L 40 40",
            },
            {
                "type": "text",
                "text": "门洞待确认",
                "x": 120,
                "y": 180,
                "font_size": 18,
                "color": "#ff3b30",
            },
        ],
    }

    put_response = client.put(
        "/api/projects/proj-1/drawings/drawing-1/annotations", json=payload
    )
    get_response = client.get("/api/projects/proj-1/drawings/drawing-1/annotations")

    assert put_response.status_code == 200
    assert get_response.status_code == 200
    assert get_response.json()["objects"] == payload["objects"]


# 功能说明：测试删除标注后，画板重置为空状态
def test_delete_annotations_resets_to_empty_board(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_drawing(session_local, models)
    client = TestClient(app)

    payload = {
        "drawing_data_version": 2,
        "schema_version": 1,
        "objects": [
            {
                "type": "text",
                "text": "保留",
                "x": 40,
                "y": 50,
                "font_size": 18,
                "color": "#ff3b30",
            }
        ],
    }

    client.put("/api/projects/proj-1/drawings/drawing-1/annotations", json=payload)
    delete_response = client.delete(
        "/api/projects/proj-1/drawings/drawing-1/annotations"
    )
    get_response = client.get("/api/projects/proj-1/drawings/drawing-1/annotations")

    assert delete_response.status_code == 200
    assert get_response.status_code == 200
    assert get_response.json()["objects"] == []


# 功能说明：测试PUT操作拒绝无效的对象类型
def test_put_rejects_invalid_object_type(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_drawing(session_local, models)
    client = TestClient(app)

    payload = {
        "drawing_data_version": 2,
        "schema_version": 1,
        "objects": [
            {
                "type": "circle",
                "x": 10,
                "y": 10,
            }
        ],
    }

    response = client.put(
        "/api/projects/proj-1/drawings/drawing-1/annotations", json=payload
    )

    assert response.status_code == 422


# 功能说明：测试PUT操作拒绝与图纸数据版本不匹配的请求
def test_put_rejects_mismatched_drawing_data_version(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)
    _seed_project_and_drawing(session_local, models)
    client = TestClient(app)

    payload = {
        "drawing_data_version": 99,
        "schema_version": 1,
        "objects": [],
    }

    response = client.put(
        "/api/projects/proj-1/drawings/drawing-1/annotations", json=payload
    )

    assert response.status_code == 409
