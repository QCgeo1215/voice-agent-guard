# Voice Visitor Agent

工业园区访客车辆登记的电话 Voice Agent demo。访客打电话 → Agent 中文自然对话采集信息 → 后端结构化保存 → 推送到微信通知"保安"放行。

> 开发中（Phase 1：后端骨架已完成）。完整架构图、部署步骤、trade-off 见 Phase 5。

## 架构（主链路）

```text
手机/网页通话 → Vapi 中文 Voice Agent → register_visitor 工具
  → FastAPI 后端 → SQLite 存储 → Server酱/pushplus → 个人微信通知
```

## 技术选型（简述，详见技术方案）

- 语音层：Vapi（托管平台，免自建电话音频流）
- 后端：FastAPI（Python）
- 存储：SQLite（demo 足够，可演进到 PostgreSQL）
- 推送：Server酱 iLink/ClawBot（主，个人微信、免企业认证）+ pushplus（备）
- 内网穿透：ngrok

## 本地运行（Windows PowerShell）

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # 然后填入 SERVERCHAN_SENDKEY
uvicorn main:app --reload --port 8000
```

测试：

```powershell
curl http://localhost:8000/health
```

## 环境变量

| 变量 | 说明 |
|---|---|
| `NOTIFIER_PROVIDER` | `serverchan` 或 `pushplus` |
| `SERVERCHAN_SENDKEY` | Server酱 SendKey（主通道） |
| `PUSHPLUS_TOKEN` | pushplus token（备用通道） |
| `NOTIFY_TIMEOUT_SECONDS` | 推送超时秒数 |
| `DATABASE_PATH` | SQLite 文件路径 |
