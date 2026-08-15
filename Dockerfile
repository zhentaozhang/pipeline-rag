# 阶段 1: builder (安装依赖)
FROM python:3.12-slim as builder

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 环境变量
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 仅复制依赖相关文件，利用 Docker 缓存
COPY pyproject.toml uv.lock ./

# 安装依赖到系统环境 (不需要虚拟环境)
RUN uv sync --frozen --no-install-project

# 阶段 2: runtime (运行环境)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 安装系统依赖 (给 unstructured 和其他解析工具用)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    poppler-utils \
    tesseract-ocr \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的包
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制项目代码
COPY . /app

EXPOSE 8080

# K8s/Docker 健康探测：每 30s 检查进程存活性
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health/liveness', timeout=5)"]

# 默认启动 API 服务（可通过 docker run --entrypoint 覆盖）
# --timeout-graceful-shutdown 60：SSE 长连接流式回答在发布/重启时可优雅跑完，
#   避免进行中的对话被硬断（第二轮架构评审·可以优化 5）。
# Celery Worker: docker run --entrypoint celery -A app.celery_app worker -l info -c 4
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "60"]
