"""一次性脚本：给 Vapi assistant 的 Deepgram transcriber 加中文 keywords 偏置。

背景：Vapi dashboard 不暴露 keywords 字段，但官方 API schema 里有
（transcriber.keywords，描述原话「公司名这类词加这里」）。keywords 仅 Nova-2/1/
Enhanced/Base 支持（Nova-3 用 keyterm）。本脚本把公司词根打进去并回读验证
Vapi/Deepgram 是否接受中文 keywords。

设计：读-改-写。先 GET 现有 transcriber（不猜 model/language），只注入 keywords，
再 PATCH，最后回读对比——回读一致即证明中文 keywords 被接受。

keywords 只放「有辨识度的公司词根」：不含常见词（物流/科技/智能…会帮倒忙），
不含整句（keywords 不支持短语），强度默认 2（从低起步，过高会误触发）。

用法（PowerShell）：
  $env:VAPI_PRIVATE_KEY="<Vapi Org Settings → API Keys → Private Key>"
  $env:VAPI_ASSISTANT_ID="<你的 assistant id，同 backend/.env>"
  python vapi/set_keywords.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.vapi.ai"

# 11 家公司的辨识词根（去掉物流/科技/智能/电子等常见词）。
KEYWORDS = [
    "晨星:2", "蓝鲸:2", "鲸鱼:2", "绿藤:2", "云杉:2", "星河:2",
    "安桥:2", "北辰:2", "海棠:2", "松果:2", "远山:2", "白泽:2",
]


def _req(method, path, key, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # 不带浏览器 UA 时 Cloudflare 会按签名拦截（403 error 1010）。
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"网络错误: {e}")
        sys.exit(1)


def main():
    key = os.environ.get("VAPI_PRIVATE_KEY")
    aid = os.environ.get("VAPI_ASSISTANT_ID")
    if not key or not aid:
        print("缺环境变量：VAPI_PRIVATE_KEY 和/或 VAPI_ASSISTANT_ID")
        sys.exit(1)

    assistant = _req("GET", f"/assistant/{aid}", key)
    transcriber = assistant.get("transcriber") or {}
    print("当前 transcriber:", json.dumps(transcriber, ensure_ascii=False))
    if transcriber.get("provider") != "deepgram":
        print(f"⚠️ 当前 provider={transcriber.get('provider')!r}，keywords 仅 Deepgram 适用")

    transcriber["keywords"] = KEYWORDS
    _req("PATCH", f"/assistant/{aid}", key, {"transcriber": transcriber})

    saved = (_req("GET", f"/assistant/{aid}", key).get("transcriber") or {}).get("keywords")
    print("回读 keywords:", json.dumps(saved, ensure_ascii=False))
    if saved == KEYWORDS:
        print("✅ Vapi 接受了中文 keywords，已生效（无需 publish，API 改即生效）")
    else:
        print("⚠️ keywords 未按预期保存——可能被 Vapi/Deepgram 拒收或改写，说明此路不通")


if __name__ == "__main__":
    main()
