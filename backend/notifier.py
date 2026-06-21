"""微信推送抽象层。
通道靠 NOTIFIER_PROVIDER 切换：
- wecom：企业微信群机器人（云上主通道，腾讯 qyapi、海外云可达稳定、免企业认证）
- serverchan / pushplus：个人微信（本地/国内出口可靠，海外云因 IP 黑洞不稳，见决策 013）
- noop：不推送（测试用）"""
import requests

from config import (
    NOTIFIER_PROVIDER,
    NOTIFY_TIMEOUT_SECONDS,
    PUSHPLUS_TOKEN,
    SERVERCHAN_API_BASE,
    SERVERCHAN_SENDKEY,
    WECOM_WEBHOOK_KEY,
)


class NotifyError(Exception):
    """推送失败（缺配置 / HTTP 错误 / 超时 / 业务错误码非 0）。"""


def send_notification(title, content):
    provider = NOTIFIER_PROVIDER.lower()
    if provider == "wecom":
        return _wecom_send(title, content)
    if provider == "serverchan":
        return _serverchan_send(title, content)
    if provider == "pushplus":
        return _pushplus_send(title, content)
    if provider == "noop":
        return {"provider": "noop", "title": title, "delivered": False}
    raise NotifyError(f"unknown NOTIFIER_PROVIDER: {NOTIFIER_PROVIDER}")


def _wecom_send(title, content):
    if not WECOM_WEBHOOK_KEY:
        raise NotifyError("WECOM_WEBHOOK_KEY is not set")
    text = content or title
    if title and content and not content.lstrip().startswith(title):
        text = f"{title}\n\n{content}"
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECOM_WEBHOOK_KEY}"
    try:
        resp = requests.post(
            url,
            json={"msgtype": "text", "text": {"content": text}},
            timeout=NOTIFY_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise NotifyError(f"wecom request failed: {e}") from e
    # 群机器人鉴权失败/限频会返回 HTTP 200 + errcode!=0，必须显式判失败
    if data.get("errcode") not in (0, None):
        raise NotifyError(f"wecom error: errcode={data.get('errcode')} {data.get('errmsg')}")
    return data


def _serverchan_send(title, content):
    if not SERVERCHAN_SENDKEY:
        raise NotifyError("SERVERCHAN_SENDKEY is not set")
    url = f"{SERVERCHAN_API_BASE.rstrip('/')}/{SERVERCHAN_SENDKEY}.send"
    try:
        resp = requests.post(
            url,
            data={"title": title, "desp": content},
            timeout=NOTIFY_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise NotifyError(f"serverchan request failed: {e}") from e


def _pushplus_send(title, content):
    if not PUSHPLUS_TOKEN:
        raise NotifyError("PUSHPLUS_TOKEN is not set")
    try:
        resp = requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "txt",
            },
            timeout=NOTIFY_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise NotifyError(f"pushplus request failed: {e}") from e
