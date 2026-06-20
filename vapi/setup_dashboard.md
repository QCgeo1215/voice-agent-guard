# Vapi 仪表盘配置清单（Phase 2）

前置：后端在跑（localhost:8000）+ cloudflared 隧道在跑。

**当前隧道地址（6/16）：**
`https://lucky-terrorists-accepting-interstate.trycloudflare.com`

注意：
- 工具接口只接受 **POST**。浏览器直接打开会显示 `Method Not Allowed`，这是正常的。
- 新版 Vapi 仪表盘里可能没有单独的 **Function** 类型，用 **API Request**（Integrations 里）即可。

---

## 方案 A（推荐）：Tools → API Request

你截图里 **INTEGRATIONS → API Request** 就是正确入口。

1. Dashboard 左侧 **Tools** → **Create Tool**
2. 选 **API Request**（蓝色插头图标）
3. 填写：
   - **Name**: `register_visitor`
   - **Description**: `Register visitor after driver confirms plate and phone. Returns JSON with a "message" field — you MUST speak that message verbatim to the driver (includes "欢迎回来" for returning visitors). Do NOT call until driver confirms the recap.`
   - **URL**: `https://lucky-terrorists-accepting-interstate.trycloudflare.com/register_visitor`
   - **Method**: `POST`
   - **Headers**（如有）: `Content-Type` = `application/json`
   - **Body / Parameters**（4 个，全部 required）：
     - `plate_number` (string) — 车牌号, 例如 沪A12345
     - `company` (string) — 来访单位
     - `phone` (string) — 访客手机号
     - `reason` (string) — 来访事由, 如送货/拜访/面试
4. **Save**

> API Request 会直接把 4 个字段 POST 成扁平 JSON 到 `/register_visitor`，后端已支持。

---

## 方案 B（备选）：Assistant 里直接加 Function

如果 API Request 配不顺，可以在 Assistant 里加：

1. **Assistants** → 你的助手 → **Functions** 标签页
2. **Add Function**
   - Function name: `register_visitor`
   - Parameters: 同上 4 个字段
   - **Server URL**: `https://lucky-terrorists-accepting-interstate.trycloudflare.com/vapi/register_visitor`
3. Save

> 这个路径走 Vapi 的 tool-calls 信封格式，后端 `/vapi/register_visitor` 已适配。

---

## 1b. 建第二个 Tool：lookup_visitor（回访识别，决策 007）

和 register 一样用 **API Request**，让 Agent 在司机报完车牌后先查回访。

- **Name**: `lookup_visitor`
- **Description**: `Look up a returning visitor by plate as soon as the driver says it. If the JSON has found=true, speak the "message" field to confirm, and if the driver agrees, reuse the returned company/reason/phone to register. If found=false, collect info normally.`
- **URL**: `https://<当前隧道地址>/lookup_visitor`
- **Method**: `POST`
- **Body / Parameters**：
  - `plate_number` (string, required) — 车牌号
  - `phone` (string, optional) — 司机若已报手机号则带上，作回访兜底键

> 备选 Function 路径走 `/vapi/lookup_visitor`（result 是紧凑 JSON 字符串），后端已适配。

---

## 2. 建 Assistant（助手）

Dashboard 左侧 **Assistants** → **Create Assistant** → 选 Blank/空白
- **Model**: OpenAI `gpt-4o-mini`（工具不稳定就换 `gpt-4o`）
- **First Message**：
  ```
  您好，车牌号多少，今天找哪家公司，什么事儿？
  ```
- **System Prompt**：复制 `vapi/system_prompt.md` 里的 System Prompt 整段
- **Transcriber（语音识别，必须改中文）**: Provider=Deepgram，Model=nova-3，**Language = `zh-CN`**
  - 重要：不设 zh-CN 会把中文按英文听成拼音乱码（如 "Da jia hao"），这是"说不了中文"的根因
  - nova-3 自 2026.3 起支持中文：`zh` / `zh-CN` / `zh-Hans`
- **Voice（语音合成，必须改中文音色）**: Provider=Azure，Voice ID=`zh-CN-XiaoxiaoNeural`（女声）或 `zh-CN-YunxiNeural`（男声）
  - 下拉找不到中文就勾 **"Add Voice ID Manually"** 手动粘贴 `zh-CN-XiaoxiaoNeural`
- **Model**: GPT-4.1 / gpt-4o 均可，本身懂中文，不用特别设置
- **Tools**: Add Tool → 同时加 `register_visitor` 和 `lookup_visitor`
- **Save**

> 配好后三张卡应显示：TRANSCRIBER=Chinese(zh-CN) / MODEL=GPT / VOICE=Xiaoxiao(Azure)。

## 3. Web 通话测试

Assistant 详情页 → **Talk to Assistant**（电脑麦克风）。说：
```
沪A12345，来蓝色鲸鱼送货，手机号 13812341234。
```

新访客验收（重点听这几点）：
1. 4 项收齐后，**必须先复述车牌+手机号问「对吗」**，司机确认后才调工具
2. 工具返回后，**必须念 message 原文**（回访时含「欢迎回来」）
3. 新访客 3-4 轮内完成登记
4. 手机号被称作"手机号"，不会说成"密码/口令"
5. 结束语清楚说出"我这就通知保安放行"（不再念成"一通之满位"）
6. 微信收到登记消息
7. 后端日志 `[register] ... elapsed_ms=...`，留意从开口到微信发出是否 < 25s

回访验收（决策 007，用上面刚登记过的同一车牌再打一通）：
```
沪A12345
```
1. Agent 报完车牌后**主动调 lookup_visitor**，念出「您之前来过，上次…今天还是一样吗？」
2. 你说「一样」→ Agent **不再逐项追问、不再复述**，直接登记并念结束语（约 2 轮完成）
3. 微信收到的消息含【回访】标注
4. 你若说「今天去别家」→ Agent 只问变化的那项，其余沿用历史

## 4. 常见问题

- **找不到 Function 类型**：正常，用 **API Request**（方案 A）。
- **浏览器打开 URL 报 405**：正常，必须用 POST。
- **语音是中文、但转录/字段变英文**：transcriber 用了会"顺手翻译"的多模态模型（如 Google gemini）。换成 **Deepgram nova-3 + Language=`zh-CN`**（纯转写不翻译，中文进中文出）。否则存库和微信字段都会变英文。
- **工具不触发**：换 `gpt-4o`，或在 prompt 里强调"信息齐全后立刻调用 register_visitor"。
- **微信没收到**：看后端 `[register]` 日志；确认 cloudflared 没关、隧道地址没变。
- **隧道地址变了**：重启 cloudflared 后会变，要同步更新 Vapi 里的 URL。

## 5. 手机二维码入口（P1）

目标：不用电脑 Vapi dashboard，让司机手机扫码进入 `/call`，点击「开始通话」后直接和同一个 Assistant 对话。

### 5.1 配置 `.env`

在 `backend/.env` 里补：

```env
VAPI_PUBLIC_KEY=<Vapi Dashboard 里的 Public Key>
VAPI_ASSISTANT_ID=<当前门卫 Assistant 的 ID>
```

改完要重启后端。

### 5.2 启动并访问

1. 启动后端：
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```
2. 启动隧道：
   ```powershell
   cloudflared tunnel --url http://localhost:8000 --protocol http2
   ```
3. 打开：
   ```text
   https://<当前隧道地址>/qr
   ```
4. 手机扫码，进入：
   ```text
   https://<当前隧道地址>/call
   ```

### 5.3 验收

- 手机页面能看到「AI 门卫访客登记」和 Vapi 的「开始通话」按钮。
- 点击后浏览器请求麦克风权限。
- Agent 使用同一个 Assistant 开场。
- `lookup_visitor` / `register_visitor` 仍正常触发。
- 微信收到登记推送。

### 5.4 注意

- 微信内置浏览器可能限制麦克风；页面已提示用系统浏览器打开。
- cloudflared 地址变了，二维码也会变；重新打开 `/qr` 生成新的即可。
- `/call` 只改变入口形态，不改变业务主链路。生产可把入口替换成真实电话 / SIP。
