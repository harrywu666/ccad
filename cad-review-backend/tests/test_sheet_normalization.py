from domain.sheet_normalization import normalize_index_no, normalize_sheet_no


# 功能说明：测试标准化空图号的处理
def test_normalize_sheet_no_empty():
    assert normalize_sheet_no("") == ""
    assert normalize_sheet_no(None) == ""


# 功能说明：测试标准化带符号和大小写的图号
def test_normalize_sheet_no_with_symbols_and_case():
    assert normalize_sheet_no(" a1-02 / (平面)") == "A102平面"


# 功能说明：测试标准化带圆圈数字的图号
def test_normalize_sheet_no_circled_number():
    assert normalize_sheet_no("A-①-03") == "A103"


# 功能说明：测试索引号使用与图号相同的标准化规则
def test_normalize_index_no_same_rule():
    assert normalize_index_no(" ②- 15 ") == "215"
