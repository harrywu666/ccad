from types import SimpleNamespace

from domain.match_scoring import (
    pick_catalog_candidate,
    score_sheet_name,
    score_sheet_no,
)


# 功能说明：测试图号完全匹配时的评分
def test_score_sheet_no_exact():
    assert score_sheet_no("A1-01", "A1-01") == 1.0


# 功能说明：测试图名相似度评分算法
def test_score_sheet_name_similarity():
    assert score_sheet_name("平面布置图", "平面布置图") == 1.0
    assert score_sheet_name("平面布置", "平面布置图") > 0.8


# 功能说明：测试目录候选选择器的阈值机制
def test_pick_catalog_candidate_threshold():
    catalogs = [
        SimpleNamespace(id="c1", sheet_no="A1-01", sheet_name="平面布置图"),
        SimpleNamespace(id="c2", sheet_no="A2-01", sheet_name="天花布置图"),
    ]
    result = pick_catalog_candidate(
        recognized_no="A1.01",
        recognized_name="平面布置",
        catalogs=catalogs,
        used_catalog_ids=set(),
        exact_sheet_no_first=True,
    )
    assert result["item"] is not None
    assert result["item"].id == "c1"


# 功能说明：测试目录候选选择器处理缺失字段的情况
def test_pick_catalog_candidate_missing_fields():
    catalogs = [SimpleNamespace(id="c1", sheet_no="", sheet_name="")]
    result = pick_catalog_candidate(
        recognized_no="",
        recognized_name="",
        catalogs=catalogs,
        used_catalog_ids=set(),
    )
    assert result["item"] is None
