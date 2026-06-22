"""车牌号校验与归一（决策 011）。

职责对标 company_registry.py：后端是权威防线，避免 ASR/LLM 听错把脏车牌写进库。

关键差异——公司是闭集，车牌是开集：
- 园区公司事先已知、数量有限，所以白名单能当"准入闸门"；公司目录是园区业务数据，入库。
- 访客车牌绝大多数是第一次来的陌生车，无法预先列出，所以车牌**不能**做"不在名单就拒绝"的闸门，
  否则会挡掉所有新访客。这里只做三件事：
    1. 省份简称闭集校验（挡假车牌 / STT 听成非省份字）；
    2. 省份首字近音纠正：手工近音表 + 拼音兜底（仅唯一命中才纠、歧义不猜，决策 015），把听岔的首字自动校回；
    3. 格式归一与校验（全角转半角、去分隔符、长度/字符规则）。
- 省份简称是国家标准常量（31 个、全国通用、十年不变），不是园区业务数据，故放代码常量、不入库；
  为它建表属于过度设计。

数字串本身（如 沪A 后面的 5~6 位）是声学开集，后端无法凭空纠错，仍依赖对话里的复述确认兜底。
"""
import re
import unicodedata

from pypinyin import Style, pinyin


class InvalidPlateError(ValueError):
    """车牌格式非法（首字非省份、长度/字符不符）。调用方据此请司机重说。"""


# 中国大陆 31 个省级行政区车牌首字（国标常量）。
PROVINCE_ABBR = frozenset("京津冀晋蒙辽吉黑沪苏浙皖闽赣鲁豫鄂湘粤桂琼渝川贵云藏陕甘青宁新")

# 省份首字近音纠错：仅当 STT 给出的首字「不在」PROVINCE_ABBR 时才查。
# key 一律是「非省份」的近音/形近字，value 是对应省份简称。
# 省份字本身不入表（不会走到这一步）；存在跨省同音（桂/贵 guì、甘 gān/赣 gàn）时，
# 因二者都是合法省份字、会直接通过校验，不进本表，故无歧义风险。
_PROVINCE_CONFUSABLE = {
    # 沪 hù
    "户": "沪", "护": "沪", "湖": "沪", "虎": "沪", "壶": "沪",
    # 苏 sū
    "速": "苏", "俗": "苏", "酥": "苏", "书": "苏", "叔": "苏",
    # 浙 zhè
    "这": "浙", "折": "浙", "哲": "浙", "者": "浙",
    # 皖 wǎn
    "完": "皖", "晚": "皖", "碗": "皖", "万": "皖",
    # 鲁 lǔ
    "路": "鲁", "卢": "鲁", "鹿": "鲁", "露": "鲁",
    # 粤 yuè
    "月": "粤", "越": "粤", "乐": "粤", "阅": "粤",
    # 京 jīng
    "经": "京", "精": "京", "惊": "京", "晶": "京",
    # 津 jīn
    "今": "津", "金": "津", "斤": "津", "巾": "津",
    # 豫 yù
    "玉": "豫", "预": "豫", "育": "豫", "誉": "豫",
    # 川 chuān
    "穿": "川", "船": "川", "串": "川",
    # 渝 yú
    "鱼": "渝", "余": "渝", "与": "渝", "雨": "渝",
    # 闽 mǐn
    "民": "闽", "敏": "闽", "闵": "闽",
    # 赣 gàn
    "赶": "赣", "感": "赣", "敢": "赣",
    # 湘 xiāng
    "香": "湘", "相": "湘", "想": "湘", "箱": "湘",
    # 冀 jì
    "既": "冀", "记": "冀", "计": "冀", "季": "冀",
    # 辽 liáo
    "了": "辽", "聊": "辽", "料": "辽", "疗": "辽",
    # 吉 jí
    "急": "吉", "级": "吉", "集": "吉", "即": "吉",
    # 琼 qióng
    "穷": "琼", "穹": "琼",
    # 云 yún
    "运": "云", "允": "云", "匀": "云",
    # 陕 shǎn
    "闪": "陕", "善": "陕",
    # 甘 gān
    "干": "甘", "肝": "甘", "尴": "甘",
    # 青 qīng
    "清": "青", "轻": "青", "情": "青", "晴": "青",
    # 宁 níng
    "您": "宁", "凝": "宁", "柠": "宁",
    # 新 xīn
    "心": "新", "信": "新", "星": "新", "辛": "新",
    # 蒙 méng
    "盟": "蒙", "梦": "蒙", "萌": "蒙",
    # 晋 jìn
    "进": "晋", "近": "晋", "劲": "晋",
    # 鄂 è
    "饿": "鄂", "恶": "鄂",
}

# —— 省份首字拼音兜底（决策 015）——
# 手工表只覆盖「想到的」近音字；这里用拼音把任意同音字自动纠回。但单字拼音有不可消除的歧义
# （桂/贵同音、京/津/晋相近），且车牌是开集、猜错＝静默写错牌没人发现，所以铁律：
# 只在「拼音唯一命中一个省」时才纠，命中 0 个或多个一律不猜，留给对话重说。
# 省份读音硬编码（单字多音，不靠 pypinyin 猜），与 heard 字的 pypinyin 同用 TONE3 制式比对。
_PROVINCE_PINYIN = {
    "京": "jing1", "津": "jin1", "冀": "ji4", "晋": "jin4", "蒙": "meng2",
    "辽": "liao2", "吉": "ji2", "黑": "hei1", "沪": "hu4", "苏": "su1",
    "浙": "zhe4", "皖": "wan3", "闽": "min3", "赣": "gan4", "鲁": "lu3",
    "豫": "yu4", "鄂": "e4", "湘": "xiang1", "粤": "yue4", "桂": "gui4",
    "琼": "qiong2", "渝": "yu2", "川": "chuan1", "贵": "gui4", "云": "yun2",
    "藏": "zang4", "陕": "shan3", "甘": "gan1", "青": "qing1", "宁": "ning2",
    "新": "xin1",
}


def _toneless(py: str) -> str:
    return py.rstrip("0123456789")


def _unique_pinyin_index(keyfn):
    """{键: 省份}，只保留唯一命中的键；多省共享的键（歧义）丢弃，从根上杜绝错猜。"""
    first, dup = {}, set()
    for prov, py in _PROVINCE_PINYIN.items():
        k = keyfn(py)
        if k in first:
            dup.add(k)
        else:
            first[k] = prov
    return {k: v for k, v in first.items() if k not in dup}


# 带声调唯一索引（分得清 京 jing1 / 津 jin1 / 晋 jin4）；无声调唯一索引（容忍 STT 听错声调）。
_TONE_TO_PROVINCE = _unique_pinyin_index(lambda py: py)
_TONELESS_TO_PROVINCE = _unique_pinyin_index(_toneless)


def _province_by_pinyin(ch: str):
    """非省份首字 → 按拼音纠回唯一命中的省；歧义或无命中返回 None（绝不猜）。

    先比带声调（区分 津/晋），不中再比无声调（容忍 STT 把 hù 听成 hú）。
    """
    got = pinyin(ch, style=Style.TONE3, heteronym=False, errors="ignore")
    if not got or not got[0] or not got[0][0]:
        return None
    py = got[0][0]
    return _TONE_TO_PROVINCE.get(py) or _TONELESS_TO_PROVINCE.get(_toneless(py))


# 省份之后的部分：城市字母码(1 位 A-Z) + 4~6 位字母数字。
# 覆盖标准 7 位车牌（省+字母+5）与新能源 8 位车牌（省+字母+6）；从宽到 4，避免误杀。
_REST_RE = re.compile(r"^[A-Z][A-Z0-9]{4,6}$")

# 中文口语数字 → 阿拉伯数字：STT/LLM 偶尔把「1」转写成「幺」、「2」转成「两」等。
# 手机号与车牌数字串都复用，做确定性归一，省得因口语写法被判错。
# 只收口语/正式数字字，不含「洞/拐」等军用谐音（是常用字，易误伤）。
_CN_DIGITS = str.maketrans({
    "零": "0", "〇": "0", "○": "0",
    "一": "1", "幺": "1", "壹": "1",
    "二": "2", "两": "2", "贰": "2",
    "三": "3", "叁": "3",
    "四": "4", "肆": "4",
    "五": "5", "伍": "5",
    "六": "6", "陆": "6",
    "七": "7", "柒": "7",
    "八": "8", "捌": "8",
    "九": "9", "玖": "9",
})


def normalize_cn_digits(s: str) -> str:
    """把中文口语/大写数字替换成阿拉伯数字（幺→1、两→2…）。非数字字符原样保留。"""
    return (s or "").translate(_CN_DIGITS)


def clean_plate(raw: str) -> str:
    """尽力归一，不抛错：全角转半角、去空格/点/横杠、字母大写、口语数字归一、首字近音纠正。

    用于回访查询等「不该因车牌脏就失败」的场景；不保证结果合法。
    """
    s = unicodedata.normalize("NFKC", raw or "").strip()
    s = re.sub(r"[\s·.\-]", "", s).upper()
    s = normalize_cn_digits(s)
    if not s:
        return ""
    province, rest = s[0], s[1:]
    if province not in PROVINCE_ABBR:
        # 手工近音表（含形近/多音字）→ 拼音兜底（仅唯一命中）→ 都不中就保留原样交给校验/重说。
        province = (_PROVINCE_CONFUSABLE.get(province)
                    or _province_by_pinyin(province)
                    or province)
    return province + rest


def normalize_plate(raw: str) -> str:
    """严格归一并校验，用于登记。非法抛 InvalidPlateError。"""
    s = clean_plate(raw)
    if len(s) < 2:
        raise InvalidPlateError(raw)
    province, rest = s[0], s[1:]
    if province not in PROVINCE_ABBR:
        raise InvalidPlateError(raw)
    if not _REST_RE.match(rest):
        raise InvalidPlateError(raw)
    return s
