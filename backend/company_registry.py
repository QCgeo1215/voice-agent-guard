"""园区公司目录与公司名标准化。

真实生产应接园区企业目录；demo 阶段用 SQLite companies/company_aliases + 候选召回 + 受限 LLM 重排。
后端标准化是权威防线，避免 ASR/LLM 听错后把脏公司名写进数据库。
"""
import json
from difflib import SequenceMatcher
from functools import lru_cache
from re import sub

import requests

from config import (
    COMPANY_RESOLVE_LLM_TIMEOUT_SECONDS,
    COMPANY_RESOLVE_USE_LLM,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
)
import db


class UnknownCompanyError(ValueError):
    def __init__(self, raw_name: str, suggestions=None):
        self.raw_name = raw_name
        self.suggestions = suggestions or []
        super().__init__(raw_name)


_DROP_WORDS = ("有限公司", "有限责任公司", "股份有限公司", "科技公司", "公司")


def standard_company_names():
    return list(_company_registry().keys())


def normalize_company(raw_name: str) -> str:
    """返回标准公司名；无法可信匹配时抛 UnknownCompanyError。"""
    raw = (raw_name or "").strip()
    key = _compact(raw)
    if not key:
        raise UnknownCompanyError(raw)

    exact = _alias_to_standard().get(key)
    if exact:
        return exact

    candidates = _rank_candidates(key)
    if not candidates:
        raise UnknownCompanyError(raw)

    top_name, top_score = candidates[0]
    second_score = candidates[1][1] if len(candidates) > 1 else 0.0
    margin = top_score - second_score
    if top_score >= 0.82 and margin >= 0.18:
        return top_name

    if COMPANY_RESOLVE_USE_LLM and LLM_API_KEY and top_score >= 0.72 and margin >= 0.12:
        judged = _llm_rerank(raw, [name for name, _ in candidates[:3]])
        if judged in standard_company_names():
            return judged
        if judged == "uncertain":
            raise UnknownCompanyError(raw, suggestions=[name for name, _ in candidates[:2]])
        if judged == "unknown":
            raise UnknownCompanyError(raw)

    if top_score >= 0.75 and margin >= 0.12:
        raise UnknownCompanyError(raw, suggestions=[top_name])
    raise UnknownCompanyError(raw)


def company_help_text() -> str:
    return "、".join(standard_company_names())


def _compact(name: str) -> str:
    text = sub(r"[\s·,，。.!！?？()（）-]", "", name or "")
    for word in _DROP_WORDS:
        text = text.replace(word, "")
    return text.lower()


def _rank_candidates(key: str):
    scores = {}
    for alias_key, standard in _alias_to_standard().items():
        score = SequenceMatcher(None, key, alias_key).ratio()
        scores[standard] = max(scores.get(standard, 0.0), score)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


@lru_cache(maxsize=1)
def _company_registry():
    """从 SQLite 读取公司目录。首次调用时若库未初始化，则初始化并导入 seed。"""
    try:
        registry = db.load_company_registry()
    except Exception:
        db.init_db()
        registry = db.load_company_registry()
    return registry


@lru_cache(maxsize=1)
def _alias_to_standard():
    aliases = {}
    for standard, meta in _company_registry().items():
        names = [standard] + meta.get("aliases", [])
        for name in names:
            aliases[_compact(name)] = standard
    return aliases


def reload_company_registry():
    """后台维护公司目录后可调用；demo 阶段主要用于测试。"""
    _company_registry.cache_clear()
    _alias_to_standard.cache_clear()


def _llm_rerank(raw_name: str, candidates: list[str]) -> str:
    """让 LLM 只在候选中选择，失败/超时一律 uncertain，保证主链路可控。"""
    if not candidates:
        return "unknown"
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    candidate_text = "、".join(candidates)
    prompt = (
        "你是园区公司名 ASR 纠错器。只能在候选公司中选择，不能创造新公司。\n"
        "输入可能有中文语音识别错字，重点判断读音/字形是否可能对应候选。\n"
        "如果明显对应某个候选，输出 JSON: {\"decision\":\"match\",\"company\":\"候选公司名\"}\n"
        "如果像某个候选但不够确定，输出 JSON: {\"decision\":\"uncertain\"}\n"
        "如果不像任何候选，输出 JSON: {\"decision\":\"unknown\"}\n"
        f"候选公司：{candidate_text}\n"
        f"用户说的公司：{raw_name}"
    )
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=COMPANY_RESOLVE_LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
    except Exception as e:
        print(f"[company_registry] LLM rerank failed, fallback to confirm: {e}")
        return "uncertain"

    decision = data.get("decision")
    company = data.get("company")
    if decision == "match" and company in candidates:
        return company
    if decision == "unknown":
        return "unknown"
    return "uncertain"

