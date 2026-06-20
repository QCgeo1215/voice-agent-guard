"""门卫查询 Agent：把门卫的自然语言问题转成对访客库的结构化查询。

设计取舍（见 README）：本场景查询模式有限、用户是内部可信门卫，
故用「LLM 抽参数 + 参数化模板 SQL」而非 text-to-SQL——零注入、零错 SQL，
LLM 只产出受白名单约束的查询意图。LLM 不可用时降级到关键词规则，demo 不中断。
"""
import json
import re
from datetime import datetime, timedelta
from typing import Optional

import requests

from company_registry import UnknownCompanyError, company_help_text, normalize_company
import db
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SECONDS

_ALLOWED_FILTERS = ("company", "date", "reason", "plate_number", "phone", "date_from", "date_to")
_ACTION_NAMES = {
    "count": "数量统计",
    "list": "明细列表",
    "summary_by_company": "按公司统计",
    "summary_by_reason": "按事由统计",
}

_INTENT_SYSTEM = """你是把门卫的中文问题转成查询参数的解析器。只输出 JSON，不要多余文字。
JSON 结构：
{
  "action": "count"、"list"、"summary_by_company" 或 "summary_by_reason",
  "filters": {
    "company": 公司关键词或null,
    "date": "today"/"yesterday"/"recent_7_days"/"this_week"/"this_month"/"YYYY-MM-DD"或null,
    "reason": "送货"/"拜访"/"面试"等或null,
    "plate_number": 车牌关键词或null,
    "phone": 手机号或null
  },
  "limit": 数字，默认10
}
问"多少/几辆/数量"用 action=count；问"有谁/列一下/最近"用 action=list。
问"哪家公司最多/按公司统计/公司分布"用 summary_by_company。
问"事由分布/都是来干嘛/按事由统计"用 summary_by_reason。
只返回 JSON。"""


def answer(question: str) -> dict:
    """主入口：解析意图 -> 执行参数化查询 -> 生成中文回答。返回 dict 便于端点封装与调试。"""
    intent = parse_intent(question)
    filters = _resolve_dates({k: intent["filters"].get(k) for k in _ALLOWED_FILTERS})
    company_error = _normalize_company_filter(filters)
    if company_error:
        return {"question": question, "intent": intent, "reply": company_error, "rows": []}
    if intent["action"] == "count":
        n = db.count_visitors(**filters)
        return {"question": question, "intent": intent, "reply": _say_count(n, filters), "count": n}
    if intent["action"] == "summary_by_company":
        rows = db.group_visitors_by("company", **filters)
        return {"question": question, "intent": intent, "reply": _say_summary(rows, filters, "公司"), "rows": rows}
    if intent["action"] == "summary_by_reason":
        rows = db.group_visitors_by("reason", **filters)
        return {"question": question, "intent": intent, "reply": _say_summary(rows, filters, "事由"), "rows": rows}
    rows = db.query_visitors(limit=intent.get("limit", 10), **filters)
    return {"question": question, "intent": intent, "reply": _say_list(rows, filters), "rows": rows}


def _normalize_company_filter(filters: dict) -> Optional[str]:
    company = filters.get("company")
    if not company:
        return None
    try:
        filters["company"] = normalize_company(company)
        return None
    except UnknownCompanyError as e:
        if e.suggestions:
            return f"园区里没直接查到「{company}」。您是不是想查：{'、'.join(e.suggestions)}？"
        return f"园区里没查到「{company}」。目前可查询的公司有：{company_help_text()}。"


def parse_intent(question: str) -> dict:
    if LLM_API_KEY:
        try:
            return _llm_parse(question)
        except Exception as e:
            print(f"[query_agent] LLM parse failed, fallback to rules: {e}")
    return _rule_parse(question)


def _llm_parse(question: str) -> dict:
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": _INTENT_SYSTEM},
            {"role": "user", "content": question},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT_SECONDS)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _normalize_intent(json.loads(content))


def _normalize_intent(raw: dict) -> dict:
    """把 LLM 输出收敛到固定结构，过滤越界字段，杜绝模型乱填导致后端出错。"""
    action = raw.get("action")
    if action not in _ACTION_NAMES:
        action = "list"
    filters = raw.get("filters")
    if not isinstance(filters, dict):
        filters = {}
    clean = {k: (filters.get(k) or None) for k in _ALLOWED_FILTERS}
    try:
        limit = int(raw.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    return {"action": action, "filters": clean, "limit": limit}


def _rule_parse(question: str) -> dict:
    """无 LLM key 时的降级解析。粗糙但能覆盖最常见问法，保证 demo 不中断。"""
    q = question or ""
    if re.search(r"(哪家|公司).*(最多|统计|分布)|按公司", q):
        action = "summary_by_company"
    elif re.search(r"(事由|来干嘛|做什么).*(统计|分布)|按事由", q):
        action = "summary_by_reason"
    elif re.search(r"(多少|几辆|几个|几人|数量|几次)", q):
        action = "count"
    else:
        action = "list"
    filters = {k: None for k in _ALLOWED_FILTERS}
    if "今天" in q or "今日" in q:
        filters["date"] = "today"
    elif "昨天" in q:
        filters["date"] = "yesterday"
    elif re.search(r"最近\s*7\s*天|近\s*7\s*天|一周内|最近一周", q):
        filters["date"] = "recent_7_days"
    elif "本周" in q or "这周" in q:
        filters["date"] = "this_week"
    elif "本月" in q or "这个月" in q:
        filters["date"] = "this_month"
    else:
        m_date = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?", q)
        if m_date:
            y, m, d = (int(x) for x in m_date.groups())
            filters["date"] = f"{y:04d}-{m:02d}-{d:02d}"
    for kw in ("送", "拜访", "面试", "维修", "开会"):
        if kw in q:
            filters["reason"] = kw
            break
    m = re.search(r"1\d{10}", q)
    if m:
        filters["phone"] = m.group()
    return {"action": action, "filters": filters, "limit": 10}


def _resolve_dates(filters: dict) -> dict:
    d = filters.get("date")
    today = datetime.now().date()
    if d == "today":
        filters["date_from"] = today.strftime("%Y-%m-%d")
        filters["date_to"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        filters["date"] = None
    elif d == "yesterday":
        start = today - timedelta(days=1)
        filters["date_from"] = start.strftime("%Y-%m-%d")
        filters["date_to"] = today.strftime("%Y-%m-%d")
        filters["date"] = None
    elif d == "recent_7_days":
        filters["date_from"] = (today - timedelta(days=6)).strftime("%Y-%m-%d")
        filters["date_to"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        filters["date"] = None
    elif d == "this_week":
        start = today - timedelta(days=today.weekday())
        filters["date_from"] = start.strftime("%Y-%m-%d")
        filters["date_to"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        filters["date"] = None
    elif d == "this_month":
        start = today.replace(day=1)
        filters["date_from"] = start.strftime("%Y-%m-%d")
        filters["date_to"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        filters["date"] = None
    return filters


def _scope_text(filters: dict) -> str:
    parts = []
    if filters.get("date"):
        parts.append(filters["date"])
    elif filters.get("date_from") or filters.get("date_to"):
        parts.append(_date_range_text(filters.get("date_from"), filters.get("date_to")))
    if filters.get("company"):
        parts.append(filters["company"])
    if filters.get("reason"):
        parts.append(filters["reason"])
    if filters.get("plate_number"):
        parts.append("车牌含" + filters["plate_number"])
    if filters.get("phone"):
        parts.append("手机号" + filters["phone"])
    return ("、".join(parts) + " ") if parts else ""


def _date_range_text(date_from, date_to) -> str:
    if not date_from and not date_to:
        return ""
    today = datetime.now().date()
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    today_s = today.strftime("%Y-%m-%d")
    yesterday_s = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if date_from == today_s and date_to == tomorrow:
        return "今天"
    if date_from == yesterday_s and date_to == today_s:
        return "昨天"
    if date_to == tomorrow:
        return f"{date_from} 至今天"
    if date_to:
        end = (datetime.strptime(date_to, "%Y-%m-%d").date() - timedelta(days=1)).strftime("%Y-%m-%d")
        return f"{date_from} 至 {end}"
    return f"{date_from} 之后"


def _say_count(n: int, filters: dict) -> str:
    scope = _scope_text(filters)
    return f"{scope}共有 {n} 条登记记录。" if scope else f"目前共有 {n} 条登记记录。"


def _say_list(rows, filters: dict) -> str:
    if not rows:
        scope = _scope_text(filters).strip()
        return f"{scope}没有查到登记记录。" if scope else "没有查到登记记录。"
    lines = [
        f"{r.get('entry_time', '')} {r['plate_number']} {r['company']} {r['reason']} {r['phone']}"
        for r in rows
    ]
    head = _scope_text(filters) or "最近"
    return f"{head}查到 {len(rows)} 条：\n" + "\n".join(lines)


def _say_summary(rows, filters: dict, label: str) -> str:
    scope = _scope_text(filters) or "当前"
    if not rows:
        return f"{scope}{label}统计没有查到登记记录。"
    lines = [f"{idx}. {r['name']}：{r['count']} 条" for idx, r in enumerate(rows, start=1)]
    return f"{scope}{label}统计：\n" + "\n".join(lines)
