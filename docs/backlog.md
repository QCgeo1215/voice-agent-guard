# 开发 Backlog

> 6/19 晚后的阶段计划见 `docs/development_plan_2026-06-19.md`。后续优先按题目要求推进：主链路验收与 25s 实测 → 手机二维码入口 → 多路并发完整链路验证 → CI/CD 与 AWS 路线 → 交付物收口。

## 已完成（6/17）
- **A. 对话系统深化** ✅：字段校验（001）+ 复述确认（002）+ 实拨验证
- **B. 回访识别** ✅：方案 C（003）+ 推送标注 + 实拨验证
- **C. 门卫查询 Agent 第一轮升级** ✅（6/18）：轻量网页后台 `/guard` + 日期范围 + 公司/事由聚合统计 + 决策 004
- **公司名标准化** ✅（6/18）：园区公司白名单 + 别名/音近错字修复 + 不存在公司反馈 + 决策 005
- **D. 多路并发评估第一轮** ✅（6/18）：SQLite busy timeout/WAL + 线程池执行登记 + noop 推送压测 + 决策 006
- **回访识别升级到理想态** ✅代码侧（6/18）：`lookup_visitor` 工具 + 第0步「主动确认 + 跳采集」+ 决策 007（升级 003）；本地验证通过，待 Vapi 接线实拨
- **回访理想态 Vapi 接线** ✅初步通过（6/19 凌晨）：`lookup_visitor` 已接入 Vapi，最新 prompt 已同步，用户实测反馈“实现了”，仍可继续优化体验
- **手机二维码入口** ✅代码侧（6/19 晚）：新增 `/call` 手机 Web Call 页 + `/qr` 二维码页 + 决策 008；本地 smoke test 通过，待填 Vapi Public Key / Assistant ID 后真机验证
- **手机二维码入口公网验证** ✅（6/19 晚）：`/qr` / `/call` 公网可达，手机可正常和 Agent 语音对话；修正 Vapi tool URL 后公网 `lookup_visitor` / `register_visitor` 自测通过，真实 Server酱推送约 `6.9s`
- **公司目录数据层** ✅（6/20 上午）：`companies` / `company_aliases` 入 SQLite，prompt 移除完整公司白名单，新增决策 009，回归验证通过
- **CI/CD + AWS 部署（代码侧）** ✅（6/20 上午）：`db.py` 双后端（SQLite/Postgres）、Dockerfile、`pytest` 冒烟、`ci.yml`（含 Postgres service）/`cd.yml`（OIDC 推 ECR）、决策 010 + `docs/deploy_aws.md`；本地测试 7 绿
- **AWS 正式上线** ✅（6/20 下午）：GitHub 仓库 + OIDC + CI/CD 全绿 → ECR 镜像 → **ECS Express Mode**（App Runner 停止接新客户后改用官方继任者）+ Neon Postgres。固定地址 `https://vo-dc486323624a436eb4cf8b9f000737d7.ecs.ap-southeast-1.on.aws`，线上 `/health` 200、`/register_visitor` 写库+微信推送 SUCCESS（后端 ~1.8s）
- **Vapi 中文音色优化** ✅（6/20 晚，控制台侧）：TTS 换 MiniMax 中文音色（治外国味）+ STT Deepgram Nova-3 + prompt 加「只说中文」（治蹦英文），已 publish
- **车牌校验数据层** ✅代码侧（6/20 晚）：新增 `backend/plate_registry.py`（省份闭集 + 近音纠错 + 归一/校验）+ 决策 011，main.py 收编内联正则，`pytest` 22 绿；**待部署生效**
- **CD 全自动部署** ✅代码侧（6/20 晚）：`cd.yml` 接官方 `amazon-ecs-deploy-express-service` Action，push 即上线（决策 010 迭代二）；**待账号侧配置**（OIDC 角色加 ECS Express 策略 + GitHub Variables/Secrets，见 `docs/deploy_aws.md` 5b）

## 下一步（按价值）
- **配齐 CD 自动部署账号侧 + 首推上线**：按 `deploy_aws.md` 5b 配 IAM 策略 + GitHub 变量/密钥 → push main → 自动部署带上车牌校验；首推盯一眼 CD 日志和服务 Healthy
- **收尾上线接线**：手机流量真机过一遍
- **必须项·25s 端到端 + 实战测试迭代**：题目硬指标至今未端到端掐表；= 考核核心「持续迭代」
- **回访体验继续打磨**：lookup 触发时机、确认话术、未命中/信息变化路径
- **多路并发完整链路验证**：2-3 台设备同时手机 Web Call + 真实微信推送，补齐 Vapi 层并发证据
- **C2. 门卫查询 Agent 可选增强**：查询页面美化 / 查询历史 / 更细时间表达（如“上周”）/ 权限提示
- **公司名标准化可选增强**：接真实企业目录 / 拼音匹配 / 人工确认候选 / 后台维护公司名单
- **D2. 并发可选增强**：真实 Server酱推送慢网测试 / 异步队列方案设计 / 更完整 trace 页面

## 靠后（开发基本完成后再做）
- 交付物：README 压一页、git 历史、demo 视频、实测记录
- 答辩材料：`docs/decisions/` 继续补（已有 001~003）
- 实拨补测：同一手机号回访确认「欢迎回来」是否说出
