# 工业园区访客语音登记 Agent (Voice Visitor Agent)

访客手机扫码 → AI 门卫中文语音对话采集（车牌 / 来访公司 / 手机号 / 事由）→ 后端结构化入库 → 企业微信群机器人通知保安放行。附「门卫查询后台」用自然语言查访客数据。

> 已云端部署，push 即上线。关键技术取舍见 [`docs/decisions/`](docs/decisions)。

## 在线体验（AWS ECS Express 固定地址）

基础地址：`https://vo-dc486323624a436eb4cf8b9f000737d7.ecs.ap-southeast-1.on.aws`

- **访客入口（手机）**：`/qr` 显示二维码 → 扫码进 `/call` → 点「开始通话」对话登记。
  - 微信内置浏览器用不了麦克风，页面会引导「右上角 → 在浏览器打开」，用系统 Chrome/Safari。
- **门卫查询后台**：`/guard`，自然语言问「今天来了几辆车 / 最近 7 天哪家公司最多 / 本月事由分布」。

![门卫智能体](./1.png)

## 核心功能

- **自然中文对话登记**：一次问清、听清不反复确认，凑齐 4 项即登记。
- **回访识别（设备身份）**：同一手机扫码＝模拟同一来电号码（localStorage 记手机号当 caller ID），回访开场即复述上次车牌/公司/事由，全程不再问手机号。
- **公司名硬白名单 + 拼音模糊匹配**：仅园区名单公司可登记；音近/误听（如「陈兴物流」→「晨星物流」）靠 pypinyin 拼音相似度召回。
- **车牌校验数据层**：31 省份简称闭集 + 近音纠错；车牌是开集，陌生车随到随登。
- **成功自动挂断**：成功语「欢迎进入园区」注册为 Vapi endCallPhrases，念完自动结束通话。
- **企业微信群推送**：走腾讯接口、海外云可达稳定、免企业认证。
- **门卫自然语言查询**：LLM 抽结构化意图 + 参数化模板 SQL（零注入、零错 SQL）；无 LLM key 自动降级关键词规则。

## 架构

```text
手机扫码 /qr → /call（Vapi Web SDK 自建 UI）
      │
      ▼
Vapi 门卫 Assistant
  STT: OpenAI gpt-4o-transcribe (zh)
  LLM: OpenAI gpt-5
  TTS: MiniMax speech-02-turbo（中文音色）
  Tools: lookup_visitor / register_visitor
      │  HTTPS
      ▼
FastAPI 后端 ── AWS ECS Express（Fargate + ALB + HTTPS，固定地址）
  ├─ 数据层  : Neon Postgres（云）/ SQLite（本地），db.py 方言适配
  ├─ 公司目录: company_registry（白名单 + 拼音模糊）
  ├─ 车牌校验: plate_registry（省份闭集 + 近音纠错）
  ├─ 推送    : 企业微信群机器人（wecom）
  └─ 查询    : query_agent（LLM 抽意图 + 参数化 SQL）

CI/CD: GitHub Actions → 测试（SQLite + Postgres）→ 构建镜像推 ECR → 部署 ECS Express
```

## 技术栈

| 层 | 选型 |
|---|---|
| 语音编排 | Vapi（STT OpenAI `gpt-4o-transcribe` / LLM OpenAI `gpt-5` / TTS MiniMax `speech-02-turbo`）|
| 后端 | FastAPI（Python）|
| 数据 | SQLite（本地）/ Neon Postgres（云），`DATABASE_URL` 切换 |
| 推送 | 企业微信群机器人（主）/ Server酱 / pushplus（备）|
| 部署 | AWS ECS Express + GitHub Actions CI/CD（push 即上线）|
| 查询 LLM | OpenAI 兼容接口（默认 DeepSeek，可留空降级关键词）|

## 本地运行（Windows PowerShell）

```powershell
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # 按需填 key；最小可只跑后端（SQLite + noop 推送）
uvicorn main:app --reload --port 8000
```

冒烟与测试：

```powershell
curl http://localhost:8000/health
python -m pytest -q          # SQLite + noop 推送，无外部依赖
```

## 主要接口

| 方法 路径 | 说明 |
|---|---|
| `GET /health` | 健康检查 |
| `POST /register_visitor` | 登记（扁平 JSON，Vapi apiRequest 工具用）|
| `POST /lookup_visitor` | 按车牌/手机号查历史（回访兜底）|
| `GET /visitors` | 全部登记记录（JSON）|
| `GET /visit/by-call/{call_id}` | 按通话取回手机号（设备身份回写）|
| `GET /call` · `GET /qr` | 手机访客入口 / 二维码 |
| `GET /guard` · `POST /guard/query` | 门卫查询后台 / 自然语言查询 |

> Vapi 信封格式另有 `/vapi/register_visitor`、`/vapi/lookup_visitor` 备用。

## 环境变量（节选，全量见 `backend/.env.example`）

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | 留空走 SQLite；填 `postgres://…` 走 Postgres |
| `NOTIFIER_PROVIDER` | `wecom`（云上主）/ `serverchan` / `pushplus` / `noop` |
| `WECOM_WEBHOOK_KEY` | 企业微信群机器人 webhook key |
| `VAPI_PUBLIC_KEY` · `VAPI_ASSISTANT_ID` | 手机 Web Call 入口 |
| `LLM_API_KEY` · `LLM_BASE_URL` · `LLM_MODEL` | 门卫查询 LLM（留空降级关键词）|

## 文档

- 关键技术取舍 · 决策记录（15 条）：[`docs/decisions/`](docs/decisions)（上云、推送通道、回访识别、公司/车牌校验等）
- 云部署运行手册：[`docs/deploy_aws.md`](docs/deploy_aws.md)
- Vapi 门卫 system prompt：[`vapi/system_prompt.md`](vapi/system_prompt.md)（需配置到 Vapi 控制台）

## 已知边界

- 设备身份是「同一浏览器」而非「同一人」；换机/清缓存优雅退回报车牌流程。
- STT 对极端测试号（如连续 8 个 1）、纯音译公司名仍有残留误差，靠 prompt 兜底重问。
- 门卫后台日期按服务器 UTC 计。

## 版权 / License

© 2026 QCgeo1215. All Rights Reserved. 保留所有权利。

本仓库为作者个人作品，仅供查看与评估之用。未经作者书面许可，禁止复制、修改、再分发或用于任何商业用途。

This repository is a personal work, provided for viewing and evaluation only. No copying, modification, redistribution, or commercial use without the author's written permission.
