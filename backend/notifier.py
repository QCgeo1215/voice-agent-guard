"""微信推送抽象层。
主通道 Server酱（iLink/ClawBot），备用 pushplus，靠环境变量 NOTIFIER_PROVIDER 切换。
两者都基于个人微信、免企业认证。"""
import requests

from config import (
    NOTIFIER_PROVIDER,
    NOTIFY_TIMEOUT_SECONDS,
    PUSHPLUS_TOKEN,
    SERVERCHAN_API_BASE,
    SERVERCHAN_SENDKEY,
)


class NotifyError(Exception):
    """推送失败（缺配置 / HTTP 错误 / 超时）。"""


def send_notification(title, content):
    provider = NOTIFIER_PROVIDER.lower()
    if provider == "serverchan":
        return _serverchan_send(title, content)
    if provider == "pushplus":
        return _pushplus_send(title, content)
    if provider == "noop":
        return {"provider": "noop", "title": title, "delivered": False}
    raise NotifyError(f"unknown NOTIFIER_PROVIDER: {NOTIFIER_PROVIDER}")


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
