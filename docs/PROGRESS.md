# 项目进度快照（2026-06-18 晚）

> 6/18 晚更新：今天继续做开发设计和系统完善，重点是门卫查询入口、公司名实体标准化，以及准备多路并发评估。
>
> 注：下方 6/15、6/16 两段是从对话记录（transcript）还原补回的——原始 6/16 快照在 6/17 收工重写时被整篇覆盖，项目当时无 git，无法逐字恢复；这两段按当日实际工作如实重建。

## 一句话
工业园区访客语音登记 Agent：网页通话 → AI 门卫问询 → 登记入库 → 微信通知保安；外加「门卫查询后台」用自然语言查访客数据。**6/18 重点做了查询后台、查询 Agent 升级、公司名标准化/实体解析、多路并发第一轮评估。**

## 技术栈（未变）
- 语音编排：Vapi（STT=Deepgram nova-3 `zh-CN` / LLM=gpt-4o-mini / TTS=Azure `zh-CN-XiaoxiaoNeural`）
- 后端：FastAPI + SQLite（`backend/`）
- 微信推送：Server酱
- 公网暴露：cloudflared 临时隧道（**本机 QUIC 不通，用 `--protocol http2`**）
- 查询 Agent LLM：OpenAI `gpt-4o-mini`

## 6/15 完成（Day 1：方案评估 + 后端骨架 + Vapi 适配，从对话记录还原）

### 方案评估与选型（第一性原理）
- 对原方案做 5 点修正；主干保留：托管语音平台（Vapi）+ 自建后端 + 微信推送，不自建音频流
- 电话穷举评估（三大运营商 / 阿里云腾讯云 / 400-95 / GoIP / Twilio / Vapi 美国号 / 香港 +852 DID）：结论=个人 7 天内拿不到合规 +86 呼入号，这本身是题目考点
- 微信：企业微信要审批 → 改 Server酱 个人微信通道为主、pushplus 为备（Notifier 抽象一键切换）

### Phase 1 后端 ✅
- `backend/`：`config.py`（配置）/ `db.py`（SQLite）/ `notifier.py`（推送抽象）/ `main.py`（接口）
- 接口：`/health` `/register_visitor` `/visitors`；SQLite 落库；服务端计时；幂等（`call_id`）
- 配套：`requirements.txt`（锁版本）/ `.env.example` / `.gitignore` / `README` 初稿
- 验证：本地接口全通；Server酱 真实推送成功（保存+推送约 3.1s），微信真实收到

### Phase 2 后端侧 ✅
- `/vapi/register_visitor`：Vapi 信封适配端点（核实当前 Vapi 工具格式，返回 `results` / `toolCallId`）
- cloudflared 隧道公网验证通过（公网 → 隧道 → 本地后端 → Server酱 → 微信 全链路）

### 资产
- `docs/phone_number_analysis.md`：电话五方案评估 + 答辩话术
- `vapi/system_prompt.md`：中文门卫 prompt + 开场白
- `vapi/setup_dashboard.md`：Vapi 仪表盘配置清单

## 6/16 完成（Day 2：端到端通关 + 话术 + 健壮性 + 门卫查询，从对话记录还原）

### Phase 2 端到端通关 ✅
- Vapi 仪表盘配 Tool + Assistant；网页中文通话端到端打通：STT/LLM/TTS + 工具 + 后端 + 微信
- 后端登记耗时约 2.4s，远低于 25s 预算

### Phase 3 话术 ✅
- 修对话质量问题：手机号不再被念成「密码」；结束语「已通知门卫」易被 TTS 念成「一通之满位」→ 改「我这就通知保安放行」
- 后端话术统一收口为中文常量（成功 / 失败 / 幂等 / 异常 / 缺字段），本地验证约 2.6s

### Phase 4 健壮性 ✅
- 全局异常兜底话术、幂等（`call_id`）、缺字段中文提示、改口 / 听不清 / 非登记意图（prompt 规则）

### 加分·门卫查询 Agent（第一版）✅
- 决策：方案 2「LLM 抽结构化意图 + 参数化模板 SQL」，不做 text-to-SQL（零注入、零错 SQL；门卫是内部可信用户）
- `/guard/query` + CLI `ask_guard.py`；规则版跑通（今天 6 条 / 最近 10 条 / 按手机号查）
- LLM 版接入：DeepSeek key 失效 → 切换 OpenAI `gpt-4o-mini`；无 key 自动降级关键词规则

### 电话 / 甲方沟通
- 核实 Vapi 免费美国号接不了国际来电；评估香港 +852 DID（个人可办、约 $4/月）
- 起草并发出「是否可提供测试呼入号」的甲方问询（见 `docs/phone_number_analysis.md`）

## 6/17 完成

### 工作方式
- 新增 `.cursor/skills/decision-point/SKILL.md`：关键选型先列方案讨论再写代码
- 新增 `.cursor/rules/take-home-mindset.mdc`：慢下来、重判断、交付靠后
- 新增 `docs/backlog.md`：开发方向排队（A→B→C→D）

### A. 对话系统深化 ✅
- **决策 001** 字段校验：后端权威（手机号 11 位 / 车牌从宽）+ prompt 软拦 + 后端回退话术 → `docs/decisions/001-字段校验位置.md`
- **决策 002** 复述确认：登记前必须复述车牌+手机号问「对吗」→ `docs/decisions/002-复述确认策略.md`
- 改动：`backend/main.py`（`_validate_fields`、`SPEECH_BAD_*`）、`vapi/system_prompt.md`（4 步登记流程）

### B. 回访识别 ✅
- **决策 003** 方案 C：不改收集流程，登记时查历史 → 推送【回访】+ 结束语「欢迎回来」→ `docs/decisions/003-回访识别.md`
- 改动：`backend/main.py`（`is_revisit`、`SPEECH_SUCCESS_REVISIT`、推送回访块）

### 实拨验证（Web Call，非真手机）
| 场景 | 结果 |
|---|---|
| 正常登记 + 微信推送 | ✅ |
| 错手机号（少一位）拦截 | ✅ |
| 回访推送【回访】标注 | ✅ |
| 登记前复述确认 | ✅（更新 Vapi prompt 后） |
| 结束语念工具 message | ✅（更新 Vapi prompt 后） |
| 回访说「欢迎回来」 | 未单独复测确认（推送已触发，prompt 更新后应 OK） |

- 后端登记 `elapsed_ms` 约 **2.7–3.6s**，远低于 25s 预算
- **重要坑**：改 `vapi/system_prompt.md` 后必须**手动粘贴到 Vapi 控制台**，仓库文件不会自动同步。今天第一次测没更新 prompt，确认/欢迎回来都没生效，更新后正常。

### HR 反馈（电话号）
- 见 `docs/phone_number_analysis.md`：不提供测试号，国外号/网页 demo 可接受，非重点

## 6/18 完成

### C. 门卫查询 Agent 第一轮升级 ✅
- 新增轻量查询后台：`GET /guard`
- 保安可输入自然语言问题，页面调用 `POST /guard/query`
- 查询 Agent 支持：
  - 数量统计：今天/昨天/最近 7 天/本周/本月
  - 明细查询：按公司、事由、手机号、车牌
  - 聚合统计：按公司 / 按事由
- 查询仍采用「LLM 抽结构化意图 + 参数化 SQL」，不做 text-to-SQL
- 决策记录：`docs/decisions/004-门卫查询入口.md`

### 公司名标准化 / 固定实体解析 ✅
- 新增 `backend/company_registry.py`
- 园区公司是固定实体，ASR 文本不能直接入库；后端标准化后再登记 / 查询
- 当前模拟公司白名单 11 家：
  - 蓝色鲸鱼科技、绿藤科技、晨星物流、云杉智能、星河电子
  - 安桥制造、北辰生物、海棠设计、松果新能源、远山材料、白泽机器人
- 支持常见简称 / 音近错字：
  - 蓝色金云科技、精于科技公司 → 蓝色鲸鱼科技
  - 绿腾科技 → 绿藤科技
  - 成兴物流 / 晨鑫物流 → 晨星物流
- 默认 fast 模式：标准名 / alias / 高置信 fuzzy 直接返回；中间置信度返回候选确认；明显未知返回公司不存在
- LLM rerank 可选：`COMPANY_RESOLVE_USE_LLM=true`，默认关闭，避免拖慢登记主链路
- 回归测试：26 个正反例通过，默认 fast 模式最大耗时约 1ms
- 决策记录：`docs/decisions/005-公司名标准化.md`

### D. 多路并发评估第一轮 ✅
- 决策记录：`docs/decisions/006-多路并发评估.md`
- 最小改造：
  - SQLite 连接增加 `timeout` / `busy_timeout`
  - 初始化启用 WAL
  - `source_call_id` 建唯一索引，避免并发重复登记
  - `/register_visitor` 和 `/vapi/register_visitor` 将同步登记核心放入线程池，避免阻塞 event loop
  - 新增 `NOTIFIER_PROVIDER=noop` 用于压测，不发真实微信
  - 响应增加 `request_id`、`push_elapsed_ms`
- 压测配置：`DATABASE_PATH=concurrency_test.db`、`NOTIFIER_PROVIDER=noop`
- 压测结果：
  - 10 个唯一登记并发：`10/10 success`，总墙钟约 `152ms`
  - 单请求后端耗时约 `52~137ms`
  - 5 个相同 `source_call_id` 并发：`5/5 success/idempotent responses`
  - 测试 DB 总记录 `11` 条，相同 `source_call_id` 只写入 `1` 条

### 加分·回访识别升级到题目理想态（lookup 工具，决策 007）✅(代码侧)
- 回顾题目原文后发现：决策 003 的「事后欢迎回来」没到题目理想态（开口主动确认、跳过采集）。推翻 003 → 决策 007。
- 后端：
  - `db.find_latest_by_plate`（精确）+ `count_by_plate`
  - `_lookup_core`：先按车牌精确查、未命中按手机号兜底，返回 `found/visit_count/company/reason/phone/last_date/message`
  - 端点 `POST /lookup_visitor`（扁平主用）+ `/vapi/lookup_visitor`（信封备用）
- prompt：新增「第 0 步 识别回访」——报完车牌即调 lookup；命中念确认句，司机说「一样」就复用历史值直接登记（~2 轮）。
- recap 复议：回访命中跳过复述确认；新访客保留决策 002。
- 本地验证（noop 推送 + 测试库）：老车牌命中(visit_count=1)、新车牌未命中、回访复用登记(欢迎回来)、车牌未命中手机号兜底(matched_by=phone) 全部正确。
- **待你接线**：Vapi 控制台新建 `lookup_visitor` 工具 + 粘最新 prompt，再实拨验证（见 `vapi/setup_dashboard.md` 回访验收）。

## 6/19 凌晨补充（Vapi 回访接线）
- Vapi 控制台已接入 `lookup_visitor`，并同步更新 Assistant 的最新版 System Prompt。
- 使用本次 cloudflared 地址 `https://moses-activists-facility-caps.trycloudflare.com`，公网 `/health` 已验证可达。
- 用户实测反馈：回访理想态已初步实现；体验仍有继续优化空间，先记录到这里。
- 待优化：继续打磨 lookup 触发时机、回访确认话术、以及异常路径（未命中 / 信息变化 / 工具未触发）。

## 6/19 晚补充（P1 手机二维码入口，代码侧）
- 先按题目重新对齐后，决定 P0 端到端实测可稍后做，先实现 P1「手机扫码呼叫 AI 门卫」入口，提升 demo 观感。
- 新增 `GET /call`：移动端访客入口，嵌入 Vapi Web Call widget；手机允许麦克风后可直接和同一个 Assistant 对话。
- 新增 `GET /qr`：按当前请求 Host 生成 `/call` 二维码；cloudflared 地址变化时重新打开 `/qr` 即可。
- 新增环境变量：`VAPI_PUBLIC_KEY`、`VAPI_ASSISTANT_ID`（已写入 `.env.example`；当前本机 `.env` 尚未填，待从 Vapi dashboard 获取）。
- 文档：`docs/decisions/008-手机端入口方案.md` 记录二维码 Web Call vs dashboard vs 真电话的取舍；`vapi/setup_dashboard.md` 增加手机入口配置与验收步骤。
- 本地 smoke test：`/call`、`/qr` 均返回 200；`/call` 在未配置 Vapi key 时显示配置提示，`/qr` 正常生成二维码页。

### P1 公网/手机验证补充
- Vapi `.env` 配置：`VAPI_PUBLIC_KEY` / `VAPI_ASSISTANT_ID` 已能被后端正常加载（不打印密钥）。
- 本次公网地址：`https://concentrations-executives-mustang-rapid.trycloudflare.com`
- 公网验证：
  - `/health` 返回 ok
  - `/call` 返回 200，Vapi widget 已加载
  - `/qr` 返回 200，二维码正常生成
- 手机端反馈：手机可以正常和 Agent 语音对话。
- 问题定位：首次登记失败是 Vapi Tool URL 只填了域名，缺少 `/lookup_visitor` / `/register_visitor` 路径；修正后公网自测通过。
- 公网工具自测：
  - `POST /lookup_visitor` 可达，未命中返回 `found=false`
  - `POST /register_visitor` 成功，真实 Server酱推送耗时约 `6.9s`
- 暴露的新工程问题：`vapi/system_prompt.md` 里包含完整公司白名单，不适合作为长期方案；明天优先评估「公司目录入库 / 后端权威化」，把 prompt 里的内部名单移到数据层。

## 6/20 上午补充（公司目录入库 / 后端权威化）
- 目标：移除 `vapi/system_prompt.md` 里的完整公司白名单，避免 prompt 和后端双份维护，也避免把业务目录暴露给 LLM。
- 新增 `backend/data/companies.json`：作为 demo seed 数据，保留 11 家公司和 alias。
- SQLite 新增数据层：
  - `companies`
  - `company_aliases`
  - `db.init_db()` 在空表时从 seed 导入，已有数据不覆盖。
- `company_registry.py` 改为从 SQLite 读取公司目录并缓存；保留原有 exact / alias / fuzzy / 可选 LLM rerank 策略。
- `vapi/system_prompt.md` 删除完整公司名单，只保留规则：公司目录由后端工具校验，Agent 不要猜，按工具 message 追问。
- 决策记录：
  - 新增 `docs/decisions/009-公司目录数据层.md`
  - 更新 `005-公司名标准化.md`，标注 prompt 白名单方案已被 009 修正。
- 验证：
  - 独立测试库 seed 成功：`11` 家公司。
  - 标准名 / alias / 音近错字回归通过（如蓝色金云科技、精于科技公司、绿腾科技、成兴物流）。
  - `py_compile` 通过，`ReadLints` 无新增问题。

## 6/20 上午补充（CI/CD + AWS 部署路线，代码侧）
痛点：cloudflared 地址每次重启都变，Vapi 工具 URL 要反复改。用户拍板「方案 C 上云」拿固定地址，并定了 **Neon Postgres + 已有 AWS 账号 + GitHub + CI/CD**。决策见 `docs/decisions/010`。

关键认知：云容器本地磁盘临时、多实例不共享，所以上云 = 必须把 SQLite 迁到外部 Postgres。这是本轮改动的核心。

已完成（不依赖 AWS 账号即可验证的代码侧）：
- `config.py` 增 `DATABASE_URL` 开关：留空走 SQLite，填 `postgres://...` 走 Postgres。
- `db.py` 抽象 `_Conn` / `_Cursor` 方言适配层，统一占位符 / 自增主键 / UPSERT / 自增 id 回取 / 唯一冲突异常；业务函数零改动，所有 DB 访问仍只经 `db.py`。
- `requirements.txt` 增 `psycopg[binary]`；新增 `requirements-dev.txt`（pytest / httpx）。
- `Dockerfile` + `.dockerignore`：FastAPI 镜像，监听 `${PORT:-8080}`，机密不进镜像。
- `backend/conftest.py` + `backend/tests/test_backend.py`：核心链路冒烟（健康检查 / 缺字段 / 登记+幂等 / 错手机号 / 未知公司 / 对话内回访 / 公司标准化），noop 推送、无外部依赖。
- `.github/workflows/ci.yml`：SQLite 测试 + **Postgres service 容器跑同一套测试** + Docker 构建校验。
- `.github/workflows/cd.yml`：测试 → 构建 → OIDC 登录 ECR → 推 `:latest` / `:sha`（App Runner 自动部署）。
- `docs/deploy_aws.md`：Neon / ECR / OIDC 角色 / GitHub Secrets / App Runner / 接线验收的一次性操作清单。

验证：
- 本地 `pytest -q`（SQLite）**7 passed**。
- Postgres 路径靠 CI 的 postgres service 持续验证（本机无 Docker / 无 Postgres，未本地跑）。

待用户操作（需 AWS 账号，见 `docs/deploy_aws.md`）：建 Neon 库、建 ECR、建 GitHub OIDC 角色、配 3 个 Secret、push、建 App Runner 服务并注入环境变量、把 Vapi 工具 URL 换成固定域名。

## 6/20 下午补充（AWS 正式上线 + App Runner→ECS Express 迭代）
当天把云部署从代码侧推到真上线，过程中踩到一个外部变动并完成迭代：

- **App Runner 停止接新客户**：6/20 建服务时发现 App Runner 自 2026-04-30 起不再接受新账号（按钮置灰）。改用 AWS 官方继任者 **Amazon ECS Express Mode**（输入相同：ECR 镜像 + 端口 + 健康检查 + 环境变量；自动建 Fargate + ALB + HTTPS + 自动扩缩）。已同步更新决策 010 与 `docs/deploy_aws.md`。
- **完整链路已建成并上线**：
  - GitHub 仓库 `QCgeo1215/voice-agent-guard`（Private）+ OIDC 角色 + 3 个 Secret。
  - CI 绿（含真 Postgres service 跑同一套测试 → 验证了本机连不上、之前没法测的 Postgres 适配层）。
  - CD 绿：构建镜像推 ECR。
  - ECS Express 服务 `voice-agent-746c` 运行中，Neon Postgres 作数据层。
- **固定公网地址**（取代 cloudflared）：
  `https://vo-dc486323624a436eb4cf8b9f000737d7.ecs.ap-southeast-1.on.aws`
- **线上端到端自测**（curl 经 --resolve 绕过校园 DNS 负缓存）：
  - `GET /health` → 200。
  - `POST /register_visitor`（蓝鲸科技→蓝色鲸鱼科技）→ success，Neon 写库 + Server酱真实微信推送 `SUCCESS`；后端 `elapsed_ms≈1778`、`push_elapsed_ms≈1596`。
- **已知小问题**：NUS 校园 DNS 对新域名有负缓存，本机/浏览器需等 TTL 过期或换手机流量；域名公网已生效（DoH 可解析）。
- **待办**：Vapi 两个工具 URL 改指固定域名（路径不变）；手机流量真机过一遍；之后更新部署用 force new deployment 或给 `cd.yml` 加 ECS 部署 Action。

## 6/20 晚补充（Vapi 中文音色优化 + 车牌校验数据层）
真机测试驱动的两处体验优化：

- **Vapi 中文语音管线升级**（控制台侧，已 publish）：之前中文「一股外国味、偶尔蹦英文」。
  - TTS：换成 **MiniMax Speech 2.5 中文音色**（Vapi humanness 榜中文最佳），外国味明显改善。
  - STT：Deepgram **Nova-3 / Multilingual**。
  - LLM：GPT-4.1；system prompt 顶部加「只说中文、禁止英文」硬约束（治蹦英文）。
  - 单轮组件延迟 ~1,075ms，远在 25s 预算内。
  - 教训：STT 一度选 Multilingual 导致中文听岔、反复追问；纯中文场景应锁中文/多语需验证。
- **车牌校验数据层（决策 011）**：朋友抓到 badcase「苏E…」被 STT 反复听岔、复述确认纠了 ~3 轮。
  - 厘清关键差异：公司是闭集（白名单当闸门、入库），**车牌是开集**（陌生访客随到随登，不能做准入闸门）。
  - 新增 `backend/plate_registry.py`：31 省份简称闭集（国标常量、不入库）+ 近音纠错表 + `clean_plate`/`normalize_plate`；main.py 收编原内联 `_PLATE_RE`，回访查询也复用省份纠正。
  - 职责对标 `company_registry.py`：后端做权威校验，prompt 不增长。
  - 诚实边界：新访客数字串（声学开集）仍靠复述确认兜底；历史车牌纠错暂不做（与回访查询重叠、有误改风险）。
  - 单测 `tests/test_plate_registry.py`；本地 `pytest` 22 绿。
- **CD 全自动部署到 ECS Express**（代码侧，决策 010 迭代二）：`cd.yml` 末尾接官方 `aws-actions/amazon-ecs-deploy-express-service@v1`，push → 测试 → 推 ECR → 自动部署，告别手动 force new deployment。
  - 关键点：Action 声明式重建 task def → 全部 env 须配进 GitHub（漏配会清空线上）；OIDC 角色要加 ECS Express 内联策略；显式指定 `container-port: 8080` + `health-check-path: /health`（默认 80//ping 会判不健康）。
  - 账号侧待办（见 `docs/deploy_aws.md` 第 5b 步）：给 OIDC 角色加策略 + 配齐 GitHub Variables/Secrets；配好后首推盯一眼。
  - **后端车牌改动随这次自动部署一起上线**（首推前先把账号侧配好；否则仍可手动 force 一次先上线车牌）。

## 关键文件（相对 6/16 有更新）
- `backend/main.py`：字段校验 + 回访识别 + `lookup_visitor` 端点
- `backend/config.py`：新增 `DATABASE_URL`（SQLite/Postgres 切换开关）
- `backend/db.py`：双后端方言适配层（`_Conn`/`_Cursor`）+ `find_latest_by_plate` / `count_by_plate`
- `backend/data/companies.json`：公司目录 seed
- `backend/company_registry.py`：从 SQLite 公司目录读取并缓存
- `backend/plate_registry.py`：车牌省份闭集 + 近音纠错 + 归一/校验（决策 011）；`tests/test_plate_registry.py` 单测
- `backend/requirements-dev.txt`、`backend/conftest.py`、`backend/tests/test_backend.py`：测试依赖与冒烟用例
- `Dockerfile` / `.dockerignore`：App Runner 镜像
- `.github/workflows/ci.yml` / `cd.yml`：CI（SQLite+Postgres+构建）/ CD（推 ECR）
- `vapi/system_prompt.md`：**最新版**（0~4 步流程：先 lookup 回访 → 收集 → 核对 → 登记 → 念 message）
- `vapi/setup_dashboard.md`：新增 `lookup_visitor` 工具配置 + 回访验收 + 手机二维码入口配置
- `docs/decisions/001~011`：十一条决策记录（003 被 007 升级，005 被 009 修正，008 手机入口，010 CI/CD+AWS，011 车牌校验数据层）
- `docs/deploy_aws.md`：AWS 部署运行手册
- `docs/backlog.md`：开发 backlog

## 如何启动（明天照这个来）
1. 后端（`backend/`）：
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```
2. 隧道（**加 http2**，本机 QUIC 会失败）：
   ```powershell
   cloudflared tunnel --url http://localhost:8000 --protocol http2
   ```
   地址重启会变 → 同步到 Vapi Tool URL，结尾 `/register_visitor`
3. Vapi：确认 System Prompt 和 Tool Description 是最新版（见 `vapi/system_prompt.md`）
4. 手机入口：
   - 后端 `.env` 填 `VAPI_PUBLIC_KEY` / `VAPI_ASSISTANT_ID`
   - 打开 `https://<当前隧道地址>/qr`，手机扫码进入 `/call`
5. 查询 Agent 自测：`.\.venv\Scripts\python.exe ask_guard.py 今天来了几辆车`

## 待办（按优先级，开发优先）
1. **AWS 上云（账号侧操作）**：按 `docs/deploy_aws.md` 建 Neon / ECR / OIDC 角色 / Secrets / App Runner，拿固定域名，换掉 cloudflared；代码侧已就绪。
2. **必须项：25s 端到端实测 + 实战测试迭代**（题目硬指标，需形成文档证据）
3. **回访体验继续打磨**：lookup 触发时机、确认话术、未命中/信息变化路径
4. **多路并发完整链路验证**：2-3 台设备同时手机 Web Call + 真实微信推送
5. **C2. 门卫查询 Agent 可选增强**：查询历史、上周/前天、页面表格化
6. **D2. 并发可选增强**：真实 Server酱推送慢网测试 / 异步队列方案设计 / 更完整 trace 页面
7. **靠后·交付**：README 压一页、git、demo 视频、实测记录
8. **靠后·答辩材料**：已有 10 条决策记录，后续选型继续补 `docs/decisions/`

CI/CD 代码侧已完成（6/20）：双后端 DB、Dockerfile、测试、`ci.yml`/`cd.yml`；待 push GitHub + 配 AWS 后生效。

## 注意 / 坑
- **Vapi prompt 双份维护**：改 `vapi/system_prompt.md` → 必须粘到 Vapi 控制台
- cloudflared 本机默认 QUIC 握手失败 → 用 `--protocol http2`
- 隧道地址重启必变
- PowerShell 中文 JSON 乱码是显示问题，数据正常
- uvicorn 干净重启：`taskkill /PID <pid> /T /F`

## 明天从哪继续
CI/CD + 双后端 DB 代码侧已就绪（本地 `pytest` 7 绿）。下一步两条线：
1. **上云拿固定地址**：按 `docs/deploy_aws.md` 完成 Neon + ECR + OIDC + App Runner，把 Vapi 工具 URL 换成固定域名，彻底告别 cloudflared 变址。
2. **回题目必须项**：用固定地址 + 手机入口跑 **25s 端到端实测 + 实战测试迭代**（正常新访客 / 回访 / 缺字段 / 改口 / 未知公司）。

本地跑测试：`cd backend; .\.venv\Scripts\python.exe -m pytest -q`。
