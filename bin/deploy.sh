#!/usr/bin/env bash
# 一键部署（幂等，可重复执行）
#
# 用法：
#   ./bin/deploy.sh                          # 基础栈（基础设施 + 业务服务）
#   ./bin/deploy.sh --with-observability     # 额外启动 Langfuse 自托管栈（profile）
#   ./bin/deploy.sh --no-build               # 跳过镜像构建（复用已有镜像）
#
# 设计：
#   - 全流程可重复执行：up -d 幂等，不会产生脏初始化状态
#   - 依赖顺序由 compose depends_on: service_healthy 保证；脚本额外做健康收敛确认
#   - 观测栈自包含（自带 PG/ClickHouse/Redis/MinIO），profile 门控，不影响基础栈
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WITH_OBS=0
DO_BUILD=1
for arg in "$@"; do
  case "$arg" in
    --with-observability) WITH_OBS=1 ;;
    --no-build) DO_BUILD=0 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg（-h 查看用法）"; exit 2 ;;
  esac
done

COMPOSE=(docker compose -f docker-compose.yml)
if [ "$WITH_OBS" = 1 ]; then
  COMPOSE+=(-f docker-compose.observability.yml --profile observability)
fi

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[deploy:error]\033[0m %s\n' "$*" >&2; }

# ── 1. 预检 ────────────────────────────────────────────────────────────────
log "预检 Docker 环境"
command -v docker >/dev/null 2>&1 || { err "未安装 docker"; exit 1; }
docker info >/dev/null 2>&1 || { err "docker daemon 未运行"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "缺少 docker compose 插件"; exit 1; }
[ -f .env ] || { err "缺少 .env（cp .env.example .env 并填写密钥）"; exit 1; }
if [ "$WITH_OBS" = 1 ]; then
  grep -q '^LANGFUSE_PUBLIC_KEY=.+' .env || log "提示：未设置 LANGFUSE_PUBLIC_KEY（Langfuse 项目自动开通需要）"
fi

# ── 2. 构建业务镜像 ────────────────────────────────────────────────────────
if [ "$DO_BUILD" = 1 ]; then
  log "构建业务镜像（app / celery 共用同一 Dockerfile）"
  "${COMPOSE[@]}" build app
else
  log "跳过镜像构建（--no-build）"
fi

# ── 3. 启动全部服务（compose 按 depends_on 健康条件排序）──────────────────
log "启动服务${WITH_OBS:+（含可观测性 profile）}"
"${COMPOSE[@]}" up -d

# ── 4. 等待健康收敛 ────────────────────────────────────────────────────────
WAIT_SECONDS="${DEPLOY_WAIT_SECONDS:-600}"
log "等待容器健康（最多 ${WAIT_SECONDS}s）"
deadline=$((SECONDS + WAIT_SECONDS))
while :; do
  # 未健康的容器（有 healthcheck 但非 healthy）
  not_ready="$("${COMPOSE[@]}" ps --format '{{.Name}} {{.Health}}' 2>/dev/null \
    | awk '$2 != "" && $2 != "healthy" {print $1"("$2")"}')"
  if [ -z "$not_ready" ]; then
    break
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    err "等待健康超时，仍未就绪：$(echo "$not_ready" | tr '\n' ' ')"
    err "排查：$("${COMPOSE[*]}" ps; echo; echo "docker compose logs <service>")"
    exit 1
  fi
  sleep 5
done

# ── 5. 汇总 ────────────────────────────────────────────────────────────────
log "容器状态："
"${COMPOSE[@]}" ps --format 'table {{.Name}}\t{{.Status}}'

app_port="$(grep -E '^APP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"
app_port="${app_port:-8080}"
log "部署完成。"
log "  应用入口     : http://localhost:${app_port}/docs"
log "  健康检查     : http://localhost:${app_port}/health/readiness"
log "  Prometheus   : http://localhost:${app_port}/metrics"
if [ "$WITH_OBS" = 1 ]; then
  lf_port="$(grep -E '^LANGFUSE_WEB_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"
  log "  Langfuse UI  : http://localhost:${lf_port:-3000}"
fi
log "分层验证：./bin/verify-deploy.sh${WITH_OBS:+ --with-observability}"
