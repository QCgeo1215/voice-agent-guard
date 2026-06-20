"""车牌归一/校验单测（决策 011）。纯函数，无需 DB / 网络。"""
import pytest

import plate_registry as pr


def test_normalize_basic():
    assert pr.normalize_plate("沪A12345") == "沪A12345"


def test_normalize_strips_and_uppercases():
    assert pr.normalize_plate(" 沪 a·12345 ") == "沪A12345"


def test_normalize_fullwidth_to_halfwidth():
    # 全角字母数字 → 半角
    assert pr.normalize_plate("沪Ａ１２３４５") == "沪A12345"


def test_new_energy_eight_char_plate():
    assert pr.normalize_plate("粤BD12345") == "粤BD12345"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("户A12345", "沪A12345"),  # 户→沪
        ("速E12345", "苏E12345"),  # 速→苏（朋友抓的 badcase 同类）
        ("月B66666", "粤B66666"),  # 月→粤
        ("今C12345", "津C12345"),  # 今→津
    ],
)
def test_province_confusable_correction(raw, expected):
    assert pr.normalize_plate(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",            # 空
        "沪",          # 太短
        "沪A",         # 主体太短
        "猫A12345",    # 首字非省份、无近音
        "X12345",      # 首字是字母而非省份
        "沪1234567",   # 城市码位不是字母
    ],
)
def test_invalid_plate_raises(raw):
    with pytest.raises(pr.InvalidPlateError):
        pr.normalize_plate(raw)


def test_clean_plate_never_raises():
    # clean 用于回访查询：尽力归一，脏数据也不抛错
    assert pr.clean_plate("户a 123") == "沪A123"
    assert pr.clean_plate("") == ""
    assert pr.clean_plate("乱七八糟") == "乱七八糟"
