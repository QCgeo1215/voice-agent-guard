"""pytest 全局配置。必须在 import config/main 之前设置环境变量，
因为 config.py 在 import 时就读取环境。测试一律走本地 SQLite + noop 推送，
不依赖任何外部服务（Postgres / Server酱 / LLM）。"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

os.environ["NOTIFIER_PROVIDER"] = "noop"
os.environ["LLM_API_KEY"] = ""
os.environ["COMPANY_RESOLVE_USE_LLM"] = "false"
# 默认本地 SQLite；CI 的 Postgres 任务会预先注入 DATABASE_URL，这里就用它跑同一套测试。
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_PATH"] = str(BACKEND_DIR / "test_visitors.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _sqlite_files():
    base = os.environ.get("DATABASE_PATH")
    if not base:
        return []
    return [Path(base), Path(base + "-wal"), Path(base + "-shm")]


@pytest.fixture(scope="session", autouse=True)
def _fresh_db():
    # SQLite：清掉旧库文件保证干净起步。Postgres（CI service）每次都是全新实例，无需清理。
    for p in _sqlite_files():
        p.unlink(missing_ok=True)
    yield
    for p in _sqlite_files():
        p.unlink(missing_ok=True)


@pytest.fixture()
def client():
    import main

    with TestClient(main.app) as c:  # with 触发 lifespan → db.init_db()
        yield c
