# FastAPI 后端镜像，给 AWS App Runner 用。
# 构建上下文是仓库根目录；只把 backend/ 放进镜像。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先装依赖，利用 Docker 层缓存
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# 再拷贝源码（.dockerignore 已排除 .env / .venv / *.db）
COPY backend/ ./

# App Runner 通过 PORT 环境变量注入端口（默认 8080）
EXPOSE 8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
