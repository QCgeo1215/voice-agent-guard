"""集中读取环境变量。所有配置只在这里读一次，其他模块从这里 import。"""
import os

from dotenv import load_dotenv

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "local")

# 数据库后端开关：
# - 留空 → 本地 SQLite（DATABASE_PATH），零依赖、易演示。
# - 填 postgres://... 或 postgresql://... → 切到 PostgreSQL（云上 App Runner + Neon）。
# 云容器本地磁盘是临时的、且多实例不共享，所以上云必须用外部 Postgres。
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "visitors.db")
DATABASE_TIMEOUT_SECONDS = float(os.getenv("DATABASE_TIMEOUT_SECONDS", "5"))
SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "5000"))

# 推送通道：serverchan | pushplus | noop
# 统一 strip()，避免 .env 里 key 前后多余空格导致鉴权失败
NOTIFIER_PROVIDER = os.getenv("NOTIFIER_PROVIDER", "serverchan").strip()

# Server酱（主通道）
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY", "").strip()
SERVERCHAN_API_BASE = os.getenv("SERVERCHAN_API_BASE", "https://sctapi.ftqq.com").strip()

# pushplus（备用通道）
PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "").strip()

# 推送 HTTP 调用超时，避免拖垮 25 秒预算
NOTIFY_TIMEOUT_SECONDS = float(os.getenv("NOTIFY_TIMEOUT_SECONDS", "8"))

# 门卫查询 Agent 的 LLM（OpenAI 兼容 /chat/completions 接口）。
# 留空则查询 Agent 自动降级为关键词规则，demo 仍可跑。
# 国内推荐 DeepSeek：LLM_BASE_URL=https://api.deepseek.com，LLM_MODEL=deepseek-chat
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat").strip()
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "12"))

# 公司实体解析只用于不确定候选的 rerank，必须短超时，避免影响登记体验。
COMPANY_RESOLVE_USE_LLM = os.getenv("COMPANY_RESOLVE_USE_LLM", "false").strip().lower() == "true"
COMPANY_RESOLVE_LLM_TIMEOUT_SECONDS = float(os.getenv("COMPANY_RESOLVE_LLM_TIMEOUT_SECONDS", "1.8"))

# 手机端 Web Call 入口（Vapi Public Key 可放前端；Assistant ID 指向已配置好的门卫 Assistant）。
VAPI_PUBLIC_KEY = os.getenv("VAPI_PUBLIC_KEY", "").strip()
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "").strip()
