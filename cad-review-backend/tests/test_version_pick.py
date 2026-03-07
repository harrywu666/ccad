from datetime import datetime, timedelta
from types import SimpleNamespace

from domain.version_pick import pick_latest_drawing, pick_latest_json


# 功能说明：测试优先选择高版本号且已匹配的图纸记录
def test_pick_latest_drawing_prefers_version_then_matched():
    rows = [
        SimpleNamespace(
            data_version=1, png_path="a.png", status="matched", page_index=1
        ),
        SimpleNamespace(data_version=2, png_path="", status="unmatched", page_index=0),
        SimpleNamespace(
            data_version=2, png_path="b.png", status="matched", page_index=2
        ),
    ]
    picked = pick_latest_drawing(rows)
    assert picked is rows[2]


# 功能说明：测试当版本号相同时，优先选择最新创建的JSON记录
def test_pick_latest_json_prefers_latest_created_at_on_tie():
    now = datetime.now()
    rows = [
        SimpleNamespace(
            data_version=2,
            json_path="a.json",
            status="matched",
            created_at=now - timedelta(minutes=2),
        ),
        SimpleNamespace(
            data_version=2, json_path="b.json", status="matched", created_at=now
        ),
    ]
    picked = pick_latest_json(rows)
    assert picked is rows[1]
