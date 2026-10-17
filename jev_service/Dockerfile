FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    JEV_MODEL=Qwen/Qwen2.5-1.5B-Instruct \
    JEV_DEVICE=cpu \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/data/cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/cache \
    && chown -R appuser:appuser /data/cache

COPY requirements.txt .

# pip 源 / 代理均可通过构建参数覆盖（国内可用清华源 + 可选代理）：
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
#                --build-arg PIP_EXTRA_INDEX_URL= \
#                --build-arg HTTPS_PROXY=http://host.docker.internal:7897 .
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_EXTRA_INDEX_URL=
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ENV PIP_DEFAULT_TIMEOUT=1000 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}
RUN HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" \
    http_proxy="${HTTP_PROXY}" https_proxy="${HTTPS_PROXY}" \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
