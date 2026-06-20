# AWS 部署运行手册（ECS Express Mode + Neon + GitHub CI/CD）

> 目标：固定公网地址 + push 即测试/部署。决策见 `docs/decisions/010`。
> 代码侧已就绪（双后端 DB、Dockerfile、测试、CI/CD 工作流）。本手册是需要账号操作的一次性步骤。
> 推荐区域：`ap-southeast-1`（新加坡），离 Neon 同区可降延迟。
>
> ⚠️ **App Runner 自 2026-04-30 起不再接受新客户**，新账号建不了。AWS 官方继任者是
> **Amazon ECS Express Mode**（同样：给 ECR 镜像 + 两个 IAM 角色 → 自动建 Fargate + ALB + HTTPS + 自动扩缩，
> 无额外费用）。本手册第 5 步用 ECS Express Mode。

---

## 0. 总览
```
GitHub push → Actions: pytest(SQLite+Postgres) → 构建镜像 → 推 ECR(:latest)
                                                              ↓
                              ECS Express Mode（Fargate + ALB + HTTPS）→ 固定 https URL
                                                              ↓
                                                  Neon PostgreSQL（DATABASE_URL）
```

## 1. Neon 数据库
1. https://neon.tech 注册，新建 Project，区域选 AWS Singapore。
2. 复制连接串，**用 Pooled connection（带 `-pooler`）**，形如：
   `postgresql://<user>:<pwd>@ep-xxx-pooler.ap-southeast-1.aws.neon.tech/<db>?sslmode=require`
3. 先验证（可选，本地装了 psycopg 的话）：把它设成 `DATABASE_URL` 跑 `pytest` 应全绿。
   - 表结构和 seed 公司目录由服务首次启动的 `db.init_db()` 自动建好，无需手动建表。

## 2. ECR 镜像仓库
控制台 ECR → Create repository（Private）→ 名字如 `voice-agent`。
或 CLI：
```bash
aws ecr create-repository --repository-name voice-agent --region ap-southeast-1
```
记下仓库名（= GitHub Secret `ECR_REPOSITORY`）。

## 3. GitHub OIDC 角色（CD 免长期密钥）
1. IAM → Identity providers → Add provider：
   - Provider URL: `https://token.actions.githubusercontent.com`
   - Audience: `sts.amazonaws.com`
2. IAM → Roles → Create role → Web identity → 选上面的 provider，Audience `sts.amazonaws.com`。
3. 信任策略改成（替换 `<ACCOUNT_ID>` / `<OWNER>` / `<REPO>`）：
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
      "StringLike": { "token.actions.githubusercontent.com:sub": "repo:<OWNER>/<REPO>:ref:refs/heads/main" }
    }
  }]
}
```
4. 权限：附加托管策略 `AmazonEC2ContainerRegistryPowerUser`（demo 够用，后续可收紧到单仓库）。
5. 记下 Role ARN（= GitHub Secret `AWS_ROLE_ARN`）。

## 4. GitHub 仓库与 Secrets
1. 新建 GitHub 仓库，把项目 push 上去（`.gitignore` 已排除 `.env` / `*.db` / `.venv`，机密不会进仓库）。
2. 仓库 Settings → Secrets and variables → Actions → 加 3 个 Secret：
   - `AWS_ROLE_ARN` = 第 3 步的 Role ARN
   - `AWS_REGION` = `ap-southeast-1`
   - `ECR_REPOSITORY` = `voice-agent`
3. push 到 `main`：
   - `CI` 工作流跑 SQLite + Postgres 两套测试 + Docker 构建校验。
   - `CD` 工作流测试通过后构建并推镜像到 ECR（`:latest` 和 `:<sha>`）。

## 5. ECS Express Mode 服务
ECR 里有 `:latest` 后，控制台 **Amazon ECS → Express Mode → Create**：
1. Container image URI：`<ACCOUNT_ID>.dkr.ecr.ap-southeast-1.amazonaws.com/voice-agent:latest`
2. Execution role：下拉 **Create new role**（自动建 `ecsTaskExecutionRole`，用于拉镜像/写日志）。
3. Infrastructure role：下拉 **Create new role**（Express 用于建 ALB/网络等）。
4. Container port：`8080`；访问类型选 **Public**。
5. Health check path：`/health`。
6. 环境变量（按需）：
   - `DATABASE_URL` = Neon pooled 连接串
   - `NOTIFIER_PROVIDER` = `serverchan`
   - `SERVERCHAN_SENDKEY` = 你的 sendkey
   - `VAPI_PUBLIC_KEY` / `VAPI_ASSISTANT_ID`（手机入口要）
   - `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`（门卫查询/公司纠错可选）
   - 不要设 `DATABASE_PATH`（留空才走 Postgres）。机密项更稳妥可放 Secrets Manager。
7. Create，几分钟后在 Resources/Timeline 拿到固定 HTTPS URL。

> 与 App Runner 的差异：Express 不自动跟 ECR `:latest`。两种更新方式：
> - 手动：控制台对服务点 **force new deployment**（零配置，但每次要点）。
> - 全自动：按下面第 5b 步配好，`cd.yml` 已接官方 `amazon-ecs-deploy-express-service` Action，push 即上线。

## 5b. CD 全自动部署（push 即上线，可选但推荐）
`cd.yml` 末尾已用官方 Action 部署 Express 服务。它是**声明式**的——每次部署按 workflow 里的配置重建 task definition，
所以**所有运行时环境变量都要在 GitHub 里配齐**，否则部署会把控制台手填的值清空。需要两件账号侧操作：

**(1) 给 OIDC 角色加 ECS Express 权限**
第 3 步那个角色（`AWS_ROLE_ARN`）原来只有 ECR 权限。IAM → 该角色 → Add permissions → Create inline policy（JSON），
粘贴（已填账号 `535079145454`，区域无关）：
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs:CreateCluster", "ecs:RegisterTaskDefinition",
        "ecs:CreateExpressGatewayService", "ecs:UpdateExpressGatewayService",
        "ecs:DescribeExpressGatewayService", "ecs:DescribeClusters",
        "ecs:DescribeServices", "ecs:ListServiceDeployments",
        "ecs:UpdateService", "ecs:DescribeServiceDeployments"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::535079145454:role/service-role/ecsTaskExecutionRole",
        "arn:aws:iam::535079145454:role/service-role/ecsInfrastructureRoleForExpressServices"
      ],
      "Condition": { "StringEquals": { "iam:PassedToService": "ecs.amazonaws.com" } }
    }
  ]
}
```
> 若你的执行/基础设施角色名不是这两个默认名，把 ARN 换成实际的（见下方怎么查）。

**(2) GitHub 加 Variables / Secrets**（Settings → Secrets and variables → Actions）

Variables（非敏感）：
| 名称 | 值 / 怎么查 |
| --- | --- |
| `ECS_SERVICE` | Express 服务名，如 `voice-agent-746c`（ECS 控制台服务页） |
| `ECS_CLUSTER` | 集群名（ECS 控制台服务所属 cluster；常为 `default`） |
| `ECS_EXECUTION_ROLE_ARN` | IAM → Roles 搜 `ecsTaskExecutionRole` → 复制 ARN |
| `ECS_INFRA_ROLE_ARN` | IAM → Roles 搜 `ecsInfrastructureRoleForExpressServices` → 复制 ARN |
| `LLM_BASE_URL` | 如 `https://api.openai.com/v1` |
| `LLM_MODEL` | 如 `gpt-4o` |
| `VAPI_ASSISTANT_ID` | Vapi Assistant ID |
| `SERVERCHAN_API_BASE` | 可选，默认 `https://sctapi.ftqq.com`（用 Server酱³ 才需改） |

Secrets（敏感，除已有 `AWS_ROLE_ARN`/`AWS_REGION`/`ECR_REPOSITORY`）：
| 名称 | 值 |
| --- | --- |
| `DATABASE_URL` | Neon pooled 连接串 |
| `SERVERCHAN_SENDKEY` | Server酱 SendKey |
| `LLM_API_KEY` | LLM key |
| `VAPI_PUBLIC_KEY` | Vapi Public Key |

> 这些值就照你现在 ECS 控制台里手填的那套**原样复制**过来，确保不漏不错。配好后第一次 push 盯一下 CD 日志和服务是否 Healthy；
> 成功后控制台手填的环境变量就由 workflow 接管，以后只改 GitHub 这一处。

## 6. 接线与验收
1. 自测：
```bash
curl https://<域名>/health
curl -X POST https://<域名>/register_visitor -H "Content-Type: application/json" \
  -d '{"plate_number":"沪A12345","company":"蓝鲸科技","phone":"13800138000","reason":"送货","source_call_id":"smoke-1"}'
```
2. 把 Vapi 两个工具 URL 改成固定域名（不再用 cloudflared）：
   - `https://<域名>/lookup_visitor`
   - `https://<域名>/register_visitor`
3. 手机入口：`https://<域名>/call`、二维码页 `https://<域名>/qr`。
4. 检查 Neon 里有新行、微信 Server酱 收到推送。
5. 之后改代码 → push main → CI 绿 → CD 推镜像并**自动部署到 ECS Express**（已配第 5b 步），域名不变；未配 5b 则手动 force new deployment。

## 故障排查
- 部署后 502/不健康：多半是端口或健康检查。确认容器端口 8080、健康检查路径 `/health`。
- DB 连接报错：确认用 Neon **pooled** 串且带 `?sslmode=require`。
- CD 卡在 AWS 登录：检查 OIDC 信任策略的 `repo:<OWNER>/<REPO>:*` 与实际仓库一致。
- 镜像推不上去：确认角色附了 ECR 权限、`ECR_REPOSITORY` 名字与 ECR 仓库一致。
- App Runner 建不了（按钮灰）：2026-04-30 后新账号不可用，按本手册用 ECS Express Mode。
- CD 部署步骤报 AccessDenied：OIDC 角色少了 5b(1) 的 ECS Express 内联策略，或 `iam:PassRole` 的角色 ARN 不对。
- 自动部署后服务挂/不推送/连不上库：多半是某个环境变量没配进 GitHub（Action 会按 workflow 重建配置）。对照 5b(2) 把缺的 Variable/Secret 补齐再 push。
- 自动部署报健康检查失败：确认 `cd.yml` 里 `container-port: 8080`、`health-check-path: /health` 没被改。
