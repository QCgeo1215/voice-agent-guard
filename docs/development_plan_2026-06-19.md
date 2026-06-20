# 6/19 晚开发计划

> 目标：回到题目原文，不按功能惯性乱加东西。先补必须项的验收与迭代证据，再做低风险高观感的加分项，最后收交付。

## 题目要求对照

### 必须交付
- 全链路跑通：已完成，网页通话 / Vapi → 后端 → 微信已通。
- 25 秒内完成：后端耗时已测，但**端到端从 Agent 开口到微信消息发出还没系统记录**。
- Human Friendly：prompt 已多轮打磨，回访理想态已初步实现，但还需要按真实场景验收。
- 可演示部署：本地 + cloudflared 已可演示。
- GitHub / README / demo 视频：靠后收口，当前先不急。
- 实战测试：还缺正式记录；这是持续迭代能力的直接证据。

### 加分项
- 门卫查询 Agent：已做第一轮，后续可打磨页面和时间表达。
- 回访识别：已从「事后欢迎回来」升级为 `lookup_visitor` 主动确认，Vapi 接线初步通过。
- 多路并发：后端 demo 级并发已验证；完整多通 Vapi + 真实微信推送还没测。
- Serverless / 云原生部署：可做，但不应压过主链路验收。AWS 可行，推荐 App Runner 路线，不建议 Lambda 重写。

## 近期优先级

### P0. 主链路验收 + 25s 实测

先做，不继续盲目加功能。

要测的场景：
- 正常新访客：一次说车牌 / 公司 / 事由，补手机号。
- 回访同车牌：报车牌后触发 `lookup_visitor`，确认「一样」后跳过采集。
- 缺字段：只缺哪个补问哪个。
- 改口：司机中途改车牌 / 公司 / 手机号。
- 未知公司：后端返回候选或白名单提示，Agent 能自然追问。

每次记录：
- 对话轮次。
- 从 Agent 开口到微信收到消息的秒数。
- 后端 `elapsed_ms` / `push_elapsed_ms`。
- 是否像真人门卫。
- 暴露的问题和下一轮改动。

产物：
- `docs/test_runs.md`：实战测试与迭代记录。
- 必要时小改 `vapi/system_prompt.md`，只改最影响体验的 1-2 个点。

完成标准：
- 至少 5 个场景有记录。
- 正常新访客和回访场景端到端 <25s。
- 至少记录一轮「发现问题 → 修改 → 复测」。

### P1. 手机二维码入口（移动端 Web Call）

目的：把 demo 从「电脑 Vapi dashboard」升级成「司机手机扫码呼叫 AI 门卫」，更贴近停车场入口场景。

推荐方案：
- 新增 `/call`：手机呼叫页，加载 Vapi Web SDK。
- 新增 `/qr`：显示当前 `/call` 链接二维码，录 demo 时电脑展示二维码，手机扫码进入。
- `.env` 增加：
  - `VAPI_PUBLIC_KEY`
  - `VAPI_ASSISTANT_ID`

为什么选它：
- 真 +86 电话个人短期拿不到，已调研并与 HR 对齐。
- Vapi dashboard 是开发者测试入口，观感差。
- 手机 Web Call 仍然让用户用手机语音完成登记，后端 / 微信 / 回访 / 并发逻辑完全复用。
- 生产环境可把入口替换成 SIP / 电话号码。

风险：
- 微信内置浏览器 / iOS Safari 可能限制麦克风，需要提示用系统浏览器打开。
- Vapi Web SDK 用法需查当前文档，不凭记忆写。
- cloudflared 地址会变，二维码要随当前地址生成。

产物：
- `GET /call`
- `GET /qr`
- `docs/decisions/008-手机端入口方案.md`
- `vapi/setup_dashboard.md` 增补 Web SDK 配置说明

完成标准：
- 手机扫码能打开呼叫页。
- 手机浏览器能和同一个 Assistant 对话。
- 微信推送仍正常。

### P2. 多路并发完整链路验证

现状：
- 后端并发已通过：10 个并发登记成功；同 `source_call_id` 竞争只写一条。
- 还没验证：多个 Vapi Web Call 同时触发工具 + 真实 Server酱推送。

下一步只做验证，不急着上队列：
- 2-3 台设备同时进入 `/call` 或 Vapi Web Call。
- 不同车牌 / 手机号同时登记。
- 观察后端日志、微信推送、数据库记录。
- 记录是否乱序、是否丢、是否明显变慢。

产物：
- 更新 `docs/decisions/006-多路并发评估.md`
- 在 `docs/test_runs.md` 追加并发实测

完成标准：
- 至少 2-3 路同时通话成功登记。
- 微信推送全部收到。
- 数据库无丢记录 / 无重复。

### P3. 公司白名单入库 / 后端权威化

今晚暴露的问题：公司白名单和别名直接写在 `vapi/system_prompt.md` 里，工程上不理想。

问题：
- prompt 和 `backend/company_registry.py` 有两份公司目录，容易不同步。
- 公司名单属于业务配置，不应暴露给 LLM prompt。
- 真实园区企业目录会变化，不应该靠改 prompt / Vapi 控制台维护。
- LLM 应负责对话，事实校验应由后端负责。

推荐方向：
- prompt 只保留原则：园区公司是固定名单，不确定不要猜，把司机说法原样传给后端；工具返回候选 / 不存在时按 message 追问。
- 后端继续作为公司解析权威。
- 将当前 `company_registry.py` 的白名单/alias 迁移到可维护数据层：
  - 第一阶段：`data/companies.json` 或 SQLite `companies` / `company_aliases` 表。
  - 第二阶段：后台维护公司名单或接真实企业目录。

候选实现：
1. JSON 配置文件：最快，适合 demo；仍能避免 prompt 泄露。
2. SQLite 表：更像生产，可和访客库共存；需要初始化 schema 和 seed 数据。
3. 远程企业目录：生产方向，当前没必要。

推荐：先做 **SQLite 表 + seed 脚本/初始化**，因为项目已经使用 SQLite，能体现“业务配置入库、后端权威校验”的工程 taste。

产物：
- `companies` / `company_aliases` 表或等价数据层。
- `company_registry.py` 改为从数据层读取。
- `vapi/system_prompt.md` 删除完整公司名单，只保留规则。
- 新增决策记录：`docs/decisions/009-公司目录数据层.md`。

完成标准：
- 公司标准化测试仍通过。
- prompt 不再包含完整内部公司白名单。
- 新增/修改 alias 不需要改 Vapi prompt。

### P4. CI/CD 与 AWS 云部署路线

判断：
- AWS 可行。
- 推荐 `AWS App Runner + PostgreSQL`，不推荐 Lambda + API Gateway 重写。
- CI 先于 CD，顺序正确。

先做 CI 基础：
- `pytest` 覆盖核心后端。
- `Dockerfile` / `.dockerignore`
- `.github/workflows/ci.yml`：安装依赖、跑测试、构建镜像。

再做 AWS CD：
- 镜像推 ECR。
- App Runner 部署 FastAPI。
- 数据库迁移 PostgreSQL（RDS / Neon 均可）。

为什么不是今晚第一优先：
- 它是加分项，不是必须项。
- 主链路 25s 和实战测试还没形成证据。
- 直接上云可能把时间花在账号 / 权限 / secrets / 数据库迁移上。

产物：
- `docs/decisions/010-CI-CD与AWS部署路线.md`
- CI 文件和 Dockerfile
- 后续再接 AWS 部署

完成标准：
- 有 GitHub 仓库后 CI 能自动跑。
- 部署前先保证测试可自动化。

### P5. 交付物收口

在主链路验收、手机入口、关键加分项记录完成后再做：
- README 压到一页：架构图、部署步骤、环境变量、测试结果、选型说明。
- demo 视频：1-2 分钟，从手机扫码 / 通话到微信收到消息。
- GitHub：commit message 清晰。
- 答辩材料：整理 001-010 决策记录，重点讲取舍和被推翻的决策。

## 今晚建议顺序

1. 启动后端 + cloudflared，做 P0 的测试记录模板和第一轮实测。
2. 若主链路问题不大，做 P1 手机二维码入口。
3. 用手机入口顺手测一次回访和端到端耗时。
4. 记录今天暴露的工程问题：公司白名单入库、CI/CD + AWS、多路并发完整链路。
5. 最后记录结果，别再扩太多功能。

## 暂不做
- 不重写 Cloudflare Workers。
- 不先做 Lambda。
- 不先做复杂队列。
- 不继续堆门卫查询 UI，除非主链路验收已经稳定。
