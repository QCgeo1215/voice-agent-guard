# Voice Agent Demo 技术方案

## 1. 项目目标

本项目目标是做一个可演示的电话 Voice Agent 访客登记系统。Demo 不追求工业级完整部署，优先保证一条链路稳定跑通：

访客拨打电话 → Voice Agent 接听 → 自然对话采集访客信息 → 后端生成结构化记录 → 推送到个人微信 → 演示“保安收到访客登记消息”。

需要采集的字段：

- 车牌号，例如：沪A12345
- 来访单位，例如：蓝色鲸鱼科技
- 手机号，例如：138xxxx1234
- 来访事由，例如：送货、拜访、面试
- 入场时间，由系统自动生成

核心交付目标：

- 可以真实用手机拨打电话
- Agent 能用中文自然对话
- 信息收集控制在 2-3 轮
- 拿齐信息后自动调用后端接口
- 后端推送完整登记信息到个人微信
- 整体从 Agent 开始说话到微信消息发出尽量控制在 25 秒内
- README 能清楚说明技术选型、部署方式、环境变量和测试结果

## 2. 推荐总方案

本项目采用“Voice Agent 平台 + 自建轻量后端 + 微信推送服务”的方案。

架构如下：

```text
手机拨打电话
    ↓
Vapi / Retell 电话 Voice Agent
    ↓
Agent 中文自然对话收集字段
    ↓
Agent 调用 tool: register_visitor
    ↓
FastAPI 后端
    ↓
SQLite 保存访客记录
    ↓
pushplus / Server酱
    ↓
个人微信收到“访客车辆登记”消息
```

推荐主线：

```text
Vapi
+ FastAPI
+ SQLite
+ pushplus
+ ngrok
```

备选主线：

```text
Retell
+ FastAPI
+ SQLite
+ Server酱
+ Cloudflare Tunnel
```

不建议主线使用：

```text
Twilio + OpenAI Realtime API 全自建电话音频流
个人微信 hook / QClaw / OpenClaw
企业级微信应用集成
前端管理后台
复杂权限系统
```

原因：

- 电话实时语音链路调试成本高，第一次做不适合全自建。
- 个人微信 hook 容易受登录状态、客户端版本和风控影响，不适合作为 demo 主链路。
- 本题的核心是端到端业务闭环、技术选型判断、自然对话体验和工程实现，不是从零实现电话基础设施。
- 一个人做 7 天 take-home，需要控制范围。

## 3. 技术栈详细说明

### 3.1 Voice Agent 平台：Vapi

主推使用 Vapi 作为电话 Voice Agent 平台。

Vapi 负责：

- 电话号码接入
- 用户来电接听
- 实时语音识别
- LLM 对话
- 中文语音合成
- 打断处理
- Tool calling
- 通话记录和 transcript

你自己负责：

- 后端接口
- 访客数据结构化保存
- 微信推送
- 技术选型说明
- Demo 视频

选择 Vapi 的原因：

- 它直接面向 voice agent 场景，不需要自己处理电话音频流。
- 支持给 assistant 配置 prompt。
- 支持 custom tools，让 Agent 在信息齐全后调用你的后端 API。
- 支持 inbound / outbound phone call。
- 对一个人做 demo 来说，开发负担最低。

潜在问题：

- 电话号码可能需要购买或绑定。
- 部分号码可能是海外号码，国内或新加坡手机号拨打时可能产生国际电话费用。
- 中文语音效果需要实际测试。
- 平台配置有学习成本，但低于自建电话流。

### 3.2 备选 Voice Agent 平台：Retell

Retell 可以作为 Vapi 的备选方案。

Retell 同样适合做：

- 电话接入
- 中文 voice agent
- 自定义 function / webhook
- 通话记录
- 通话后分析

选择 Retell 的场景：

- Vapi 电话号码或计费卡住
- Vapi 中文语音效果不满意
- Retell 的控制台配置更顺手
- Retell 的号码购买或导入更容易

实现方式和 Vapi 基本一致：

```text
Retell Agent
    ↓ custom function
FastAPI /register_visitor
    ↓
pushplus / Server酱
```

### 3.3 不作为主线的方案：Twilio + OpenAI Realtime API

Twilio + OpenAI Realtime API 是更底层、更工程化的方案，但不建议作为第一版主线。

它的大致结构是：

```text
用户拨打 Twilio 号码
    ↓
Twilio Voice Media Streams
    ↓ WebSocket
你的后端服务
    ↓ WebSocket
OpenAI Realtime API
    ↓
返回音频给 Twilio
    ↓
用户听到 Agent 语音
```

优点：

- 架构更可控
- 技术含量更高
- 可以更好展示底层工程能力
- 后续扩展空间大

缺点：

- 第一次做容易卡在 WebSocket、音频格式、延迟、打断、错误恢复
- 开发时间不可控
- 很可能主链路还没稳定，README 和 demo 时间就不够
- take-home 项目风险过高

结论：

- 可以在 README 的技术选型说明里作为“备选方案”讨论。
- 不建议作为主实现。

### 3.4 后端框架：FastAPI

后端使用 FastAPI。

原因：

- Python 上手快。
- 定义接口和数据模型很直接。
- Pydantic 很适合校验 Agent 传来的结构化字段。
- 本地启动简单。
- 和 SQLite、requests/httpx 集成容易。
- Demo 项目不需要复杂后端框架。

后端职责：

- 提供 `/health` 健康检查接口
- 提供 `/register_visitor` 接收 Agent tool call
- 校验字段是否完整
- 自动补充入场时间
- 保存记录到 SQLite
- 推送微信消息
- 返回成功/失败状态给 Voice Agent
- 记录耗时和错误日志

推荐接口：

```text
GET  /health
POST /register_visitor
GET  /visitors
GET  /visitors/search?plate_number=沪A12345
```

第一版只必须实现：

```text
GET  /health
POST /register_visitor
```

### 3.5 数据库：SQLite

第一版用 SQLite，不用 PostgreSQL。

原因：

- 无需部署数据库服务。
- 本地文件即可保存数据。
- 适合 demo。
- 后续可以平滑迁移到 PostgreSQL。
- 回访识别只需要简单查表。

访客表设计：

```sql
CREATE TABLE visitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number TEXT NOT NULL,
    company TEXT NOT NULL,
    phone TEXT NOT NULL,
    reason TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    source_call_id TEXT,
    raw_payload TEXT,
    created_at TEXT NOT NULL
);
```

字段说明：

- `plate_number`: 车牌号
- `company`: 来访单位
- `phone`: 手机号
- `reason`: 来访事由
- `entry_time`: 入场时间
- `source_call_id`: Vapi / Retell 通话 ID，可选
- `raw_payload`: 原始请求，方便 debug
- `created_at`: 后端创建时间

### 3.6 微信推送：pushplus

主推 pushplus。

Demo 场景下，pushplus 的作用是把后端消息推送到你的个人微信。它不是个人微信机器人，也不需要你模拟微信聊天协议。

流程：

```text
后端生成访客登记文本
    ↓
POST pushplus API
    ↓
你的微信收到推送
```

选择 pushplus 的原因：

- 配置简单
- 适合个人 demo
- 可以推送到微信
- 不需要企业微信组织
- 不需要维护微信客户端在线
- 不需要接触个人微信 hook

推送内容示例：

```text
访客车辆登记

车牌号：沪A12345
来访单位：蓝色鲸鱼科技
手机号：138xxxx1234
来访事由：送货
入场时间：2026-06-15 10:23:18

状态：待保安确认放行
```

### 3.7 微信推送备选：Server酱

Server酱也可以作为备选。

它的定位也是通过 SendKey 调接口，把消息推送到个人微信相关入口。

适合场景：

- pushplus 不稳定
- pushplus 配置卡住
- Server酱接收体验更好

代码层面可以把推送服务抽象成一个接口：

```text
Notifier
  ├── PushPlusNotifier
  └── ServerChanNotifier
```

环境变量控制使用哪个：

```env
NOTIFIER_PROVIDER=pushplus
PUSHPLUS_TOKEN=xxx
SERVERCHAN_SENDKEY=xxx
```

### 3.8 本地公网暴露：ngrok

Vapi / Retell 调你的本地后端时，需要一个公网 HTTPS 地址。

本地开发推荐 ngrok：

```bash
ngrok http 8000
```

然后你会得到类似：

```text
https://xxxx.ngrok-free.app
```

Voice Agent tool URL 配置为：

```text
https://xxxx.ngrok-free.app/register_visitor
```

ngrok 的好处：

- 配置快
- 适合 webhook 调试
- 能看到请求记录
- 本地电脑即可 demo

注意：

- 免费域名可能会变。
- 每次重启 ngrok 后，要检查 URL 是否变化。
- demo 前不要临时重启。

### 3.9 本地公网暴露备选：Cloudflare Tunnel

Cloudflare Tunnel 也可以用：

```bash
cloudflared tunnel --url http://localhost:8000
```

它会生成一个临时公网 URL。

适合场景：

- ngrok 网络不稳定
- ngrok 免费额度受限
- 需要另一个备选 tunnel

注意：

- Quick Tunnel 更适合测试开发，不建议当生产部署。
- demo 前要确认公网地址没有变化。

### 3.10 部署方式

第一版只要求本地可运行。

推荐本地部署：

```text
本地 FastAPI
+ ngrok
+ Vapi / Retell 云端
+ pushplus / Server酱
```

可选云部署：

```text
Render / Railway / Fly.io
+ SQLite 或 Neon PostgreSQL
```

本题没有必要第一版就上完整 serverless。

可在 README 中写：

“本项目主版本支持本地部署演示。由于 take-home 时间有限，优先保证电话登记到微信通知的端到端闭环。后续可将 FastAPI 部署到 Render/Railway/Fly.io，并将 SQLite 替换为 Neon PostgreSQL。”

## 4. 关键数据流

### 4.1 正常访客登记流程

```text
1. 访客拨打 Vapi / Retell 分配的电话号码
2. Voice Agent 接听
3. Agent 询问：车牌号、来访单位、来访事由
4. 用户回答
5. Agent 判断缺少手机号
6. Agent 追问手机号
7. 用户回答手机号
8. Agent 调用 register_visitor tool
9. 后端接收 JSON
10. 后端补充 entry_time
11. 后端写入 SQLite
12. 后端调用 pushplus / Server酱
13. 你的个人微信收到访客登记消息
14. Agent 告诉用户：已通知门卫，请稍等放行
```

### 4.2 回访识别流程

回访识别是可选加分项。

```text
1. 用户来电
2. Agent 或后端根据 caller number / plate_number / phone 查询历史记录
3. 如果发现历史记录，Agent 简化提问
4. 用户确认
5. 后端复用历史公司、事由、手机号
6. 推送微信
```

如果平台拿不到 caller number，也可以在用户说出车牌后再查历史记录。

第一版回访识别可以这样做：

```text
用户：沪A12345。
Agent：查到上次是来蓝色鲸鱼送货，今天还是一样吗？
用户：对。
Agent：好的，已通知门卫，请稍等。
```

不一定非要开场就识别。

## 5. Agent Prompt 设计

### 5.1 Prompt 目标

Prompt 目标不是让 Agent 很会聊天，而是让它：

- 少废话
- 问得自然
- 一次问多个字段
- 不机械逐项问
- 不重复问已经给过的信息
- 信息齐全后立刻调用 tool
- 控制总时长
- 对车牌、手机号做简单确认
- 不问无关问题，例如预计停留多久

### 5.2 推荐 Prompt

```text
你是工业园区入口的真人门卫风格语音助手。你的任务是在最短时间内帮访客车辆完成登记，并通知门卫放行。

你需要采集以下信息：
1. 车牌号
2. 来访单位
3. 手机号
4. 来访事由

入场时间由系统自动记录，不需要询问用户。

对话要求：
- 使用中文，语气自然、简短，像真人门卫。
- 不要机械式一问一答。
- 第一次开口尽量合并询问：车牌号、来访单位、来访事由。
- 用户已经说过的信息不要重复询问。
- 如果只缺手机号，只问手机号。
- 如果只缺一个字段，只补问这个字段。
- 信息齐全后，立刻调用 register_visitor 工具。
- 工具调用成功后，只说一句：“好的，已通知门卫，请稍等放行。”
- 不要解释系统流程。
- 不要问预计停留多久。
- 不要问姓名，除非用户主动说。
- 不要闲聊。
- 全程目标控制在 2-3 轮对话。

开场白：
“您好，车牌号多少，今天找哪家公司，什么事儿？”

字段理解：
- “蓝鲸”“蓝色鲸鱼”“WhaleTech”都可以理解为“蓝色鲸鱼科技”。
- “送东西”“送货”“配送”都可以归为“送货”。
- “面试”“来面试”都可以归为“面试”。
- 中国车牌可能包含中文省份简称、字母和数字，例如“沪A12345”。

调用 register_visitor 工具时，必须传入：
- plate_number
- company
- phone
- reason
```

## 6. Tool Schema 设计

Voice Agent 工具名：

```text
register_visitor
```

用途：

```text
Register a visitor vehicle and notify the security guard.
```

参数：

```json
{
  "type": "object",
  "properties": {
    "plate_number": {
      "type": "string",
      "description": "Visitor vehicle plate number, for example 沪A12345"
    },
    "company": {
      "type": "string",
      "description": "Target company inside the park"
    },
    "phone": {
      "type": "string",
      "description": "Visitor phone number"
    },
    "reason": {
      "type": "string",
      "description": "Reason for visit, such as delivery, meeting, interview"
    }
  },
  "required": ["plate_number", "company", "phone", "reason"]
}
```

Tool URL：

```text
https://你的-ngrok-url/register_visitor
```

Method：

```text
POST
```

Headers：

```text
Content-Type: application/json
```

## 7. 后端接口设计

### 7.1 POST /register_visitor

请求：

```json
{
  "plate_number": "沪A12345",
  "company": "蓝色鲸鱼科技",
  "phone": "13812341234",
  "reason": "送货"
}
```

响应：

```json
{
  "success": true,
  "message": "visitor registered and notification sent",
  "entry_time": "2026-06-15 10:23:18"
}
```

失败响应：

```json
{
  "success": false,
  "message": "missing required field: phone"
}
```

### 7.2 GET /health

响应：

```json
{
  "status": "ok"
}
```

### 7.3 GET /visitors

用于 demo 后展示记录，不一定要接到 Agent。

响应：

```json
[
  {
    "id": 1,
    "plate_number": "沪A12345",
    "company": "蓝色鲸鱼科技",
    "phone": "13812341234",
    "reason": "送货",
    "entry_time": "2026-06-15 10:23:18"
  }
]
```

## 8. 后端代码骨架

### 8.1 requirements.txt

```text
fastapi
uvicorn[standard]
pydantic
python-dotenv
requests
sqlalchemy
```

### 8.2 .env.example

```env
APP_ENV=local
DATABASE_URL=sqlite:///./visitors.db

NOTIFIER_PROVIDER=pushplus

PUSHPLUS_TOKEN=your_pushplus_token
SERVERCHAN_SENDKEY=your_serverchan_sendkey

NOTIFICATION_TIMEOUT_SECONDS=5
```

### 8.3 main.py 示例

```python
import os
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

load_dotenv()

app = FastAPI(title="Voice Visitor Agent Backend")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./visitors.db")
NOTIFIER_PROVIDER = os.getenv("NOTIFIER_PROVIDER", "pushplus")
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN")
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


class VisitorRequest(BaseModel):
    plate_number: str = Field(..., description="Vehicle plate number")
    company: str = Field(..., description="Target company")
    phone: str = Field(..., description="Visitor phone number")
    reason: str = Field(..., description="Reason for visit")
    source_call_id: Optional[str] = None


def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number TEXT NOT NULL,
            company TEXT NOT NULL,
            phone TEXT NOT NULL,
            reason TEXT NOT NULL,
            entry_time TEXT NOT NULL,
            source_call_id TEXT,
            raw_payload TEXT,
            created_at TEXT NOT NULL
        )
        """))


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register_visitor")
def register_visitor(payload: VisitorRequest):
    entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    created_at = datetime.now().isoformat(timespec="seconds")

    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO visitors (
                plate_number,
                company,
                phone,
                reason,
                entry_time,
                source_call_id,
                raw_payload,
                created_at
            )
            VALUES (
                :plate_number,
                :company,
                :phone,
                :reason,
                :entry_time,
                :source_call_id,
                :raw_payload,
                :created_at
            )
            """),
            {
                "plate_number": payload.plate_number,
                "company": payload.company,
                "phone": payload.phone,
                "reason": payload.reason,
                "entry_time": entry_time,
                "source_call_id": payload.source_call_id,
                "raw_payload": payload.model_dump_json(),
                "created_at": created_at,
            }
        )

    content = format_visitor_message(payload, entry_time)
    push_result = push_notification("访客车辆登记", content)

    return {
        "success": True,
        "message": "visitor registered and notification sent",
        "entry_time": entry_time,
        "push_result": push_result,
    }


@app.get("/visitors")
def list_visitors():
    with engine.begin() as conn:
        rows = conn.execute(text("""
        SELECT id, plate_number, company, phone, reason, entry_time, created_at
        FROM visitors
        ORDER BY id DESC
        LIMIT 20
        """)).mappings().all()

    return [dict(row) for row in rows]


def format_visitor_message(payload: VisitorRequest, entry_time: str) -> str:
    return f"""访客车辆登记

车牌号：{payload.plate_number}
来访单位：{payload.company}
手机号：{payload.phone}
来访事由：{payload.reason}
入场时间：{entry_time}

状态：待保安确认放行
"""


def push_notification(title: str, content: str):
    if NOTIFIER_PROVIDER == "pushplus":
        return pushplus_send(title, content)

    if NOTIFIER_PROVIDER == "serverchan":
        return serverchan_send(title, content)

    raise HTTPException(status_code=500, detail="Invalid NOTIFIER_PROVIDER")


def pushplus_send(title: str, content: str):
    if not PUSHPLUS_TOKEN:
        raise HTTPException(status_code=500, detail="PUSHPLUS_TOKEN is missing")

    resp = requests.post(
        "https://www.pushplus.plus/send",
        json={
            "token": PUSHPLUS_TOKEN,
            "title": title,
            "content": content,
            "template": "txt"
        },
        timeout=5,
    )

    resp.raise_for_status()
    return resp.json()


def serverchan_send(title: str, content: str):
    if not SERVERCHAN_SENDKEY:
        raise HTTPException(status_code=500, detail="SERVERCHAN_SENDKEY is missing")

    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    resp = requests.post(
        url,
        data={
            "title": title,
            "desp": content
        },
        timeout=5,
    )

    resp.raise_for_status()
    return resp.json()
```

### 8.4 本地启动

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

Windows PowerShell：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn main:app --reload --port 8000
```

测试：

```bash
curl http://localhost:8000/health
```

手动测试登记：

```bash
curl -X POST http://localhost:8000/register_visitor \
  -H "Content-Type: application/json" \
  -d '{
    "plate_number": "沪A12345",
    "company": "蓝色鲸鱼科技",
    "phone": "13812341234",
    "reason": "送货"
  }'
```

## 9. Vapi / Retell 配置步骤

### 9.1 创建 Voice Agent

配置项：

```text
Language: Chinese / Mandarin
Voice: 中文自然语音
Model: 平台默认推荐模型，或 GPT-4o-mini / Claude / Gemini 中延迟较低的模型
First message: 您好，车牌号多少，今天找哪家公司，什么事儿？
Prompt: 使用上方门卫 prompt
```

### 9.2 添加 Tool

Tool name：

```text
register_visitor
```

Tool description：

```text
Register a visitor vehicle after all required information is collected.
```

URL：

```text
https://你的-ngrok-url/register_visitor
```

Method：

```text
POST
```

Parameters：

```json
{
  "plate_number": "string",
  "company": "string",
  "phone": "string",
  "reason": "string"
}
```

### 9.3 绑定电话号码

两种方式：

```text
方案 A：使用 Vapi / Retell 平台购买或分配的号码
方案 B：导入 Twilio 号码
```

Demo 优先使用方案 A。

如果是海外号码：

- 提前确认自己的手机能拨通。
- 录 demo 前测试至少 3 次。
- demo 视频里可以说明使用的是 demo number。

## 10. 25 秒目标的实现策略

25 秒目标的关键不是模型多强，而是对话设计。

### 10.1 对话轮数控制

推荐目标：

```text
AI 开场：5 秒内
用户第一轮回答：5-8 秒
AI 补问手机号：2 秒
用户第二轮回答：3-5 秒
Agent tool call + 微信推送：1-3 秒
AI 结束语：1 秒
```

理想总耗时：

```text
15-20 秒
```

### 10.2 Prompt 控制

必须避免：

```text
请问您的车牌号是多少？
请问您来访哪家公司？
请问您来访事由是什么？
请问您的手机号是多少？
请问您预计停留多久？
```

推荐：

```text
您好，车牌号多少，今天找哪家公司，什么事儿？
```

### 10.3 后端控制

后端接口要快：

- 不做复杂鉴权
- 不等外部数据库
- 不做长流程
- 微信推送 timeout 控制在 5 秒以内
- SQLite 写入很快
- 返回内容简短

### 10.4 失败兜底

如果微信推送失败：

第一版可以返回失败，让 Agent 说：

```text
信息已登记，但通知门卫失败，请稍等人工处理。
```

实际 demo 前要先确认 pushplus / Server酱正常。

## 11. Demo 对话脚本

### 11.1 正常登记

```text
AI：您好，车牌号多少，今天找哪家公司，什么事儿？
用户：沪A12345，来蓝色鲸鱼送货。
AI：收到，手机号方便留一下吗？
用户：13812341234。
AI：好的，已通知门卫，请稍等放行。
```

微信收到：

```text
访客车辆登记

车牌号：沪A12345
来访单位：蓝色鲸鱼科技
手机号：13812341234
来访事由：送货
入场时间：2026-06-15 10:23:18

状态：待保安确认放行
```

### 11.2 用户一次性说全

```text
AI：您好，车牌号多少，今天找哪家公司，什么事儿？
用户：沪A12345，蓝色鲸鱼面试，手机号13812341234。
AI：好的，已通知门卫，请稍等放行。
```

### 11.3 用户漏说公司

```text
AI：您好，车牌号多少，今天找哪家公司，什么事儿？
用户：沪A12345，送货。
AI：找哪家公司？手机号也方便一起说一下。
用户：蓝色鲸鱼，13812341234。
AI：好的，已通知门卫，请稍等放行。
```

### 11.4 回访识别

```text
AI：您好，车牌号多少，今天找哪家公司，什么事儿？
用户：沪A12345。
AI：查到上次是来蓝色鲸鱼送货，今天还是一样吗？
用户：对，手机号也一样。
AI：好的，已通知门卫，请稍等放行。
```

## 12. 测试计划

### 12.1 功能测试

| 测试项 | 输入 | 期望 |
|---|---|---|
| 正常登记 | 车牌、公司、事由、手机号 | 微信收到完整消息 |
| 一次性说全 | 一句话包含全部字段 | Agent 不重复追问 |
| 漏手机号 | 第一轮没说手机号 | Agent 只追问手机号 |
| 漏公司 | 第一轮没说公司 | Agent 只补问公司 |
| 中文车牌 | 沪A12345 | 后端保存正确 |
| 手机号 | 13812341234 | 后端保存正确 |
| 微信推送失败 | 错 token | 后端返回错误 |
| 重复来访 | 同车牌第二次来 | 可触发回访识别 |

### 12.2 体验测试

找 2-3 个朋友拨打测试，记录：

```text
测试人：
测试时间：
是否拨通：
总耗时：
Agent 是否自然：
是否重复追问：
字段是否识别正确：
微信是否收到：
问题：
修改：
```

### 12.3 性能目标

```text
电话接通后到微信收到消息：<= 25 秒
正常流程对话轮数：2-3 轮
后端 /register_visitor 响应：<= 2 秒
微信推送成功率：demo 前连续 5 次成功
```

## 13. 风险和 fallback

### 13.1 电话号码无法使用

风险：

- 平台号码购买失败
- 海外号码拨不通
- 计费或实名认证卡住

Fallback：

- 同时注册 Vapi 和 Retell
- 优先用平台分配号码
- 备选导入 Twilio 号码
- 如果实在拨号受限，录屏展示平台测试 call，但 README 明确说明电话接入卡点和已验证部分

### 13.2 中文识别不好

Fallback：

- 换 voice / model
- 缩短 prompt
- 让用户按 demo script 测试
- 在 README 写明中文车牌识别是主要挑战
- 对车牌做简单确认

### 13.3 微信推送失败

Fallback：

- pushplus 和 Server酱都准备
- 后端 notifier 可通过环境变量切换
- demo 前不要修改 token
- 本地 curl 先确认能推送

### 13.4 ngrok URL 变化

Fallback：

- demo 前固定启动 ngrok
- 不要中途重启
- 每次重启后更新 Vapi / Retell tool URL
- 备选 Cloudflare Tunnel

### 13.5 Agent 不调用 tool

Fallback：

- 在 prompt 中明确：信息齐全后必须立刻调用 register_visitor
- Tool schema required 字段写清楚
- 第一版不要让 Agent 做复杂判断
- 如果平台支持 structured extraction / call analysis，也可用通话结束后 webhook 作为备选，但主线仍推荐实时 tool call

## 14. README 建议结构

README 控制在一页左右，但可以链接到 `docs/technical_plan.md`。

推荐 README：

```md
# Voice Visitor Agent

A phone-based voice agent demo for industrial park visitor vehicle registration.

## Architecture

Phone call → Vapi Voice Agent → FastAPI backend → SQLite → pushplus / ServerChan → WeChat notification

## Features

- Real inbound phone call demo
- Chinese voice conversation
- Collects plate number, company, phone, reason
- Sends visitor record to WeChat
- Stores visitor records in SQLite
- Optional repeated visitor recognition

## Tech Stack

- Voice Agent: Vapi
- Backend: FastAPI
- Database: SQLite
- Notification: pushplus / ServerChan
- Local tunnel: ngrok
- Language: Python

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

```bash
ngrok http 8000
```

Set the public URL as the Vapi tool endpoint:

```text
https://xxx.ngrok-free.app/register_visitor
```

## Environment Variables

```env
DATABASE_URL=sqlite:///./visitors.db
NOTIFIER_PROVIDER=pushplus
PUSHPLUS_TOKEN=xxx
SERVERCHAN_SENDKEY=xxx
```

## Demo Script

AI: 您好，车牌号多少，今天找哪家公司，什么事儿？  
User: 沪A12345，来蓝色鲸鱼送货。  
AI: 收到，手机号方便留一下吗？  
User: 13812341234。  
AI: 好的，已通知门卫，请稍等放行。

## Trade-offs

This demo uses Vapi for the phone and real-time voice layer, while the business backend and WeChat notification are self-built. I chose this approach because the take-home focuses on end-to-end delivery, conversation quality, tool calling, and architecture judgment. A fully self-built Twilio + Realtime API implementation would provide more control, but it has higher integration risk within a 7-day deadline.
```

## 15. GitHub commit 计划

推荐 commit 粒度：

```text
init project structure
add FastAPI health endpoint
add visitor registration API
add SQLite visitor storage
add pushplus notification service
add serverchan notification fallback
add Vapi tool schema and prompt
add ngrok deployment instructions
add demo script and test cases
add repeated visitor lookup
update README with architecture and tradeoffs
```

## 16. AI Coding 使用方式

可以在答辩中说明：

```text
我使用 AI Coding 辅助生成 FastAPI 项目骨架、Pydantic model、SQLite 初始化代码和 README 初稿。
但核心架构选择、接口边界、tool schema、prompt 设计、微信推送 fallback 和测试用例是我自己判断后确定的。
对 AI 生成代码的审查重点包括：
1. 是否存在过度工程化
2. 是否有硬编码密钥
3. webhook 是否有 timeout
4. 环境变量是否可配置
5. 接口字段是否和 voice agent tool schema 一致
6. 失败场景是否可观察
```

## 17. 最终建议范围

必须完成：

```text
电话能打通
Agent 中文接听
2-3 轮采集字段
调用 FastAPI
SQLite 保存
个人微信收到推送
README + demo 视频
```

可以加：

```text
回访识别
GET /visitors
测试记录
Server酱 fallback
```

不要做：

```text
完整前端后台
企业级权限
多路并发
门卫自然语言查询 Agent
个人微信 hook
Twilio + Realtime 全自建主线
```

## 18. 结论

这套方案可以做出来，而且适合一个人完成。

核心思想是：

```text
电话实时语音层用成熟平台托管；
业务后端、结构化登记、存储和微信推送自己实现；
主链路做稳，再加一个轻量回访识别作为亮点。
```

最终交付看起来应该是：

```text
一个真实可拨打的电话 demo
一个能收到微信通知的完整登记链路
一个清楚说明 trade-off 的 GitHub 仓库
一个 1-2 分钟演示视频
```

## 19. 参考资料

- Vapi Assistants Quickstart: https://docs.vapi.ai/assistants/quickstart
- Vapi Tools: https://docs.vapi.ai/tools
- Vapi Custom Tools: https://docs.vapi.ai/tools/custom-tools
- Retell Custom Function: https://docs.retellai.com/build/conversation-flow/custom-function
- Retell Webhook Overview: https://docs.retellai.com/features/webhook-overview
- ngrok Docs: https://ngrok.com/docs/start
- Cloudflare Tunnel Quick Tunnels: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
- pushplus API: https://www.pushplus.plus/doc/guide/api.html
- Server酱: https://sct.ftqq.com/
