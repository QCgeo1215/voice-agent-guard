"""核心后端链路冒烟测试：登记 / 幂等 / 字段校验 / 公司标准化 / 对话内回访。
全部走 SQLite + noop 推送，CI 无需任何外部依赖。"""
import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_register_missing_fields(client):
    r = client.post("/register_visitor", json={"plate_number": "沪A12345"})
    body = r.json()
    assert body["success"] is False
    assert "还缺" in body["message"]


def test_register_success_and_idempotent(client):
    payload = {
        "plate_number": "沪A88888",
        "company": "蓝鲸科技",  # 别名 → 标准名 蓝色鲸鱼科技
        "phone": "13800138000",
        "reason": "送货",
        "source_call_id": "call-test-1",
    }
    r = client.post("/register_visitor", json=payload)
    assert r.json()["success"] is True
    # 同一 source_call_id 再来一次 → 幂等话术，不重复登记
    r2 = client.post("/register_visitor", json=payload)
    assert "登记过" in r2.json()["message"]


def test_bad_phone(client):
    r = client.post(
        "/register_visitor",
        json={
            "plate_number": "沪A12345",
            "company": "绿藤科技",
            "phone": "123",
            "reason": "拜访",
        },
    )
    assert r.json()["success"] is False


def test_unknown_company(client):
    r = client.post(
        "/register_visitor",
        json={
            "plate_number": "沪A12345",
            "company": "完全不相关的随机词",
            "phone": "13800138000",
            "reason": "拜访",
        },
    )
    assert r.json()["success"] is False


def test_lookup_revisit(client):
    plate = "粤B66666"
    reg = client.post(
        "/register_visitor",
        json={
            "plate_number": plate,
            "company": "云杉智能",
            "phone": "13900139000",
            "reason": "面试",
            "source_call_id": "call-test-2",
        },
    )
    assert reg.json()["success"] is True

    r = client.post("/lookup_visitor", json={"plate_number": plate})
    body = r.json()
    assert body["found"] is True
    assert body["company"] == "云杉智能"
    assert body["visit_count"] >= 1


def test_company_normalization():
    import company_registry as cr

    cr.reload_company_registry()
    assert cr.normalize_company("蓝鲸") == "蓝色鲸鱼科技"
    with pytest.raises(cr.UnknownCompanyError):
        cr.normalize_company("完全不相关的随机词")


def test_company_pinyin_and_english_aliases():
    """STT 把中文公司名识别成拼音/英文音译时，别名应能命中标准名（与车牌近音纠错同思路）。"""
    import company_registry as cr

    cr.reload_company_registry()
    # 拼音（大小写/空格不敏感，经 _compact 归一）
    assert cr.normalize_company("chenxing") == "晨星物流"
    assert cr.normalize_company("Chen Xing Wu Liu") == "晨星物流"
    # 英文直译
    assert cr.normalize_company("blue whale") == "蓝色鲸鱼科技"
    assert cr.normalize_company("morning star") == "晨星物流"
