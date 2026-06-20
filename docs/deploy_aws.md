# AWS 部署运行手册（App Runner + Neon + GitHub CI/CD）

> 目标：固定公网地址 + push 即测试/部署。决策见 `docs/decisions/010`。
> 代码侧已就绪（双后端 DB、Dockerfile、测试、CI/CD 工作流）。本手册是需要账号操作的一次性步骤。
> 推荐区域：`ap-southeast-1`（新加坡），离 Neon 同区可降延迟。

---

## 0. 总览
```
GitHub push → Actions: pytest(SQLite+Postgres) → 构建镜像 → 推 ECR(:latest)
                                                              ↓ 自动部署
                                        App Runner 拉 :latest → 固定 https 域名
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

## 5. App Runner 服务
ECR 里有 `:latest` 后，控制台 App Runner → Create service：
1. Source：Container registry → Amazon ECR → 选 `voice-agent:latest`。
2. Deployment trigger：**Automatic**（推新 `:latest` 自动上线）。
3. ECR access role：让控制台自动创建（AppRunnerECRAccessRole）。
4. Service settings：
   - Port：`8080`
   - 环境变量（按需）：
     - `DATABASE_URL` = Neon pooled 连接串
     - `NOTIFIER_PROVIDER` = `serverchan`
     - `SERVERCHAN_SENDKEY` = 你的 sendkey
     - `VAPI_PUBLIC_KEY` / `VAPI_ASSISTANT_ID`（手机入口要）
     - `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`（门卫查询/公司纠错可选）
     - 机密项更稳妥的做法是放 Secrets Manager / SSM，再在 App Runner 引用。
   - Health check：HTTP，路径 `/health`。
5. Create & deploy，几分钟后拿到固定域名：`https://xxxx.ap-southeast-1.awsapprunner.com`。

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
5. 之后改代码 → push main → CI 绿 → CD 推镜像 → App Runner 自动上线，域名不变。

## 故障排查
- 部署后 502/不健康：多半是端口或启动命令。确认 App Runner Port=8080，容器 `CMD` 用 `${PORT:-8080}`。
- DB 连接报错：确认用 Neon **pooled** 串且带 `?sslmode=require`。
- CD 卡在 AWS 登录：检查 OIDC 信任策略的 `repo:<OWNER>/<REPO>:ref:refs/heads/main` 与实际仓库/分支一致。
- 镜像推不上去：确认角色附了 ECR 权限、`ECR_REPOSITORY` 名字与 ECR 仓库一致。
