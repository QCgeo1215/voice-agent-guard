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
    "raw,expected",
    [
        ("庐A12345", "鲁A12345"),  # 庐(lú)→鲁：手工表没有，靠无声调唯一命中
        ("襟B12345", "津B12345"),  # 襟(jīn)→津：靠声调区分 津jin1/晋jin4
        ("禁C12345", "晋C12345"),  # 禁(jìn)→晋
        ("扇D12345", "陕D12345"),  # 扇(shàn)→陕：容忍声调差（陕=shǎn）
        ("葬E12345", "藏E12345"),  # 葬(zàng)→藏
    ],
)
def test_province_pinyin_fallback(raw, expected):
    assert pr.normalize_plate(raw) == expected


@pytest.mark.parametrize("ch", ["跪", "鸡", "宇"])  # 桂/贵、冀/吉、豫/渝 同音歧义
def test_province_pinyin_ambiguous_not_guessed(ch):
    # 拼音命中多个省时绝不猜，留给对话重说（车牌猜错＝静默写错牌）
    assert pr._province_by_pinyin(ch) is None
    with pytest.raises(pr.InvalidPlateError):
        pr.normalize_plate(ch + "A12345")


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
    assert pr.clean_plate("乱码") == "乱码"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("幺三五", "135"),       # 幺→1
        ("两壹零", "210"),       # 两→2 壹→1 零→0
        ("13800138000", "13800138000"),  # 纯阿拉伯数字不变
    ],
)
def test_normalize_cn_digits(raw, expected):
    assert pr.normalize_cn_digits(raw) == expected


def test_plate_with_spoken_digits():
    # STT 把车牌数字串听成口语数字（幺二三四五）也能归一
    assert pr.normalize_plate("沪A幺二三四五") == "沪A12345"
