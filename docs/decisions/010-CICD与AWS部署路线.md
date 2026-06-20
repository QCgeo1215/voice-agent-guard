# 010 CI/CD 与 AWS 云部署路线

## 背景 / 约束
- 题目加分项：serverless / 云原生部署 + CI/CD。
- 直接痛点：本地 `cloudflared` 隧道每次重启都换公网地址，Vapi 工具 URL 要反复改，演示很烦。需要一个**固定公网地址**。
- 现状：FastAPI + 本地 SQLite 单文件，靠 cloudflared 临时暴露。
- 用户决策（6/20）：选「方案 C：上云」，接受较大改动；数据库用 Neon、已有 AWS 账号、走 GitHub + CI/CD。

## 一个绕不开的前提：SQLite 必须换 Postgres
云容器（App Runner / Fargate 等）本地磁盘是临时的、重启即丢、多实例不共享。
所以「上云」实质 = 把存储迁到外部托管数据库。这才是本次改动大的真正原因，不是部署本身。

## 候选方案

### 计算服务
1. ~~**AWS App Runner（原计划）**~~：托管容器服务，最贴近「serverless 容器」。**但 2026-04-30 起不再接受新客户**，本项目新账号建不了，已放弃。
2. **Amazon ECS Express Mode（实际采用）**：AWS 官方指定的 App Runner 继任者。给 ECR 镜像 + 两个 IAM 角色，自动建 Fargate + ALB + HTTPS + 自动扩缩，无额外费用，运维同样少；完整复用我们的 ECR 镜像与 CI/CD。
3. **ECS Fargate（标准）+ ALB**：更可控，但要自己配 ALB / target group / 证书，配置量大；Express 本质是它的简化封装。
4. **Lambda + API Gateway**：最「serverless」，但 FastAPI 要包 Mangum、冷启动/二进制依赖（psycopg）更麻烦，等于重写部署形态。
5. **EC2**：最灵活但要自己管机器、进程、证书，违背少运维目标。

### 数据库
1. **Neon PostgreSQL（本次采用）**：Serverless Postgres，免费额度够 demo，只要一个 `DATABASE_URL`，几分钟开通，自带连接池端点。
2. **AWS RDS PostgreSQL**：全在 AWS 里，但要配 VPC connector 才能让 App Runner 访问、成本更高、开通更慢。
3. **Supabase / 自建**：可行但无额外收益。

### 部署 / CI-CD 拓扑
1. **App Runner 源码连接（GitHub）+ 托管运行时**：最简单，但用托管 runtime 不走 Dockerfile，且测试仍要另配。
2. **GitHub Actions → 构建镜像 → 推 ECR → App Runner 自动部署（本次采用）**：CI（pytest）+ CD（build/push）一条龙，复用 Dockerfile，最能体现 CI/CD 加分；App Runner 对 ECR 仓库开「自动部署」，推 `:latest` 即上线。

## 最终选择
**Amazon ECS Express Mode（计算）+ Neon PostgreSQL（数据）+ GitHub Actions（CI/CD，OIDC 推 ECR）。**

> 迭代记录（6/20）：原计划用 App Runner，落地时发现它 2026-04-30 起停止接收新客户、新账号按钮置灰。
> 改用 AWS 官方继任者 ECS Express Mode——输入相同（ECR 镜像 + 端口 + 健康检查 + 环境变量），
> 仅「自动跟随 ECR latest」这一点需用 force new deployment 或额外 GitHub Action 补上。这正是「持续迭代 / 方案随约束变化」的实例。
>
> 迭代记录二（6/20 晚）：补齐 CD 最后一公里。`cd.yml` 末尾接官方 `aws-actions/amazon-ecs-deploy-express-service@v1`，
> push → 测试 → 推 ECR → **自动部署 Express 服务**，不再手动 force new deployment。
> 关键约束：该 Action 是声明式（每次按 workflow 重建 task definition），所以**全部运行时环境变量须配进 GitHub**（Secrets/Variables），
> 否则部署会清空控制台手填的值；并需给 OIDC 角色加 ECS Express 内联策略（`*ExpressGatewayService` + `iam:PassRole`）。
> 容器端口 `8080`、健康检查 `/health` 必须在 Action 入参里显式指定（其默认是 80 / `/ping`，否则判不健康）。
> 取舍：手动只需点一下、零风险；全自动一次性配置成本更高、且会接管线上环境变量，但换来 push 即上线、配置集中在 GitHub 一处。本项目选全自动以做满 CI/CD 加分。

代码侧改动（本轮已完成，未依赖 AWS 账号即可验证）：
- `config.py` 增 `DATABASE_URL` 开关：留空走本地 SQLite，填 `postgres://...` 走 Postgres。
- `db.py` 抽象出 `_Conn` / `_Cursor` 方言适配层，统一占位符（`?`→`%s`）、自增主键（`AUTOINCREMENT`↔`IDENTITY`）、UPSERT（`INSERT OR IGNORE`↔`ON CONFLICT`）、自增 id 回取（`lastrowid`↔`RETURNING id`）、唯一冲突异常。业务函数不感知后端类型。
- `requirements.txt` 增 `psycopg[binary]`；新增 `requirements-dev.txt`（pytest / httpx）。
- `Dockerfile` + `.dockerignore`：构建 FastAPI 镜像，监听 `PORT`（App Runner 默认 8080）。
- `tests/test_backend.py` + `conftest.py`：核心链路冒烟测试（登记/幂等/校验/公司标准化/回访），noop 推送、无外部依赖。
- `.github/workflows/ci.yml`：SQLite 测试 + **Postgres service 容器跑同一套测试** + Docker 构建校验。
- `.github/workflows/cd.yml`：测试 → 构建 → OIDC 登录 ECR → 推 `:latest` 与 `:sha`。

AWS 侧步骤（需账号操作，见 `docs/deploy_aws.md`）：建 ECR 仓库 → 建 GitHub OIDC IAM 角色 → 配 GitHub Secrets → 首推镜像 → 建 App Runner 服务（注入 `DATABASE_URL` 等环境变量、健康检查 `/health`、开启自动部署）。

## 理由
- 固定公网域名一次性解决「地址老变」的痛点，Vapi 工具 URL 不再频繁改。
- App Runner 运维最少，最贴合「serverless 容器」叙事。
- 双后端适配让本地仍可零依赖跑 SQLite，云上才用 Postgres，开发体验不退化。
- CI 里用真实 Postgres service 跑测试，持续验证云路径，不靠「上线才知道行不行」。
- OIDC 免长期密钥，符合安全最佳实践。

## 已知代价 / 可演进
- `db.py` 用轻量方言适配而非 ORM；够当前规模，复杂查询变多时可迁 SQLAlchemy。
- 每次请求新建 DB 连接；高并发下建议用 Neon 的 **pooled 连接串**，或后续加连接池。
- App Runner 最小实例常驻有基础费用；纯 scale-to-zero 可后续评估。
- 首次上云仍有账号/IAM/Secrets 一次性配置成本，已在 `docs/deploy_aws.md` 固化为清单。

## 被否决 / 暂不做
- 不重写成 Lambda + API Gateway（FastAPI 形态改动大、收益低）。
- 不走 Cloudflare Workers 重写（与当前 Python 栈不匹配）。
- 暂不用 RDS（VPC 配置与成本高于 demo 需要）。
