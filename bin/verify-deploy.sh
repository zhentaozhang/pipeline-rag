#!/usr/bin/env bash
# 部署后分层验证（自下而上；只看 docker ps 不足以证明系统可用）
#
# 用法：
#   ./bin/verify-deploy.sh                     # 基础栈
#   ./bin/verify-deploy.sh --with-observability # 额外验证 Langfuse 栈
#
# 分层：
#   L1 容器层       —— 容器 running / healthy
#   L2 应用健康层   —— /health/liveness + /health/readiness
#   L3 基础设施层   —— app→依赖 逐项状态 + mysql/redis 容器内直探
#   L4 业务链路层   —— 登录取 token → 真实业务读接口 → 返回真实数据
#   L5 监控层       —— /metrics 聚合指标非空
#
# 说明：基础设施直探一律走 `docker compose exec`（容器内），避免宿主机端口
# 与其它系统（如 ticketflow 占用 3306/9200/6379）冲突导致误判。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WITH_OBS=0
for arg in "$@"; do
  case "$arg" in
    --with-observability) WITH_OBS=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg"; exit 2 ;;
  esac
done

COMPOSE=(docker compose -f docker-compose.yml)
if [ "$WITH_OBS" = 1 ]; then
  COMPOSE+=(-f docker-compose.observability.yml --profile observability)
fi

APP_PORT="$(grep -E '^APP_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"
APP_PORT="${APP_PORT:-8080}"
BASE="http://localhost:${APP_PORT}"

FAILED=0
pass() { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
fail() { printf '  \033[1;31m✗\033[0m %s\n' "$*"; FAILED=$((FAILED + 1)); }
layer() { printf '\n\033[1;34m== %s ==\033[0m\n' "$*"; }
json_get() { python3 -c "import json,sys;d=json.load(sys.stdin);print(eval(sys.argv[1],{'d':d}))" "$1" 2>/dev/null; }

# ── L1 容器层 ──────────────────────────────────────────────────────────────
layer "L1 容器层"
ps_out="$("${COMPOSE[@]}" ps --format '{{.Name}} {{.State}} {{.Health}}' 2>/dev/null)"
while read -r name state health; do
  [ -z "${name:-}" ] && continue
  if [ "$state" != "running" ]; then
    fail "${name} 状态=${state}"
  elif [ -n "$health" ] && [ "$health" != "healthy" ]; then
    fail "${name} 健康=${health}"
  else
    pass "${name} running${health:+/$health}"
  fi
done <<< "$(echo "$ps_out" | grep -v '^$')"

# ── L2 应用健康层 ──────────────────────────────────────────────────────────
layer "L2 应用健康层"
if code="$(curl -s -o /dev/null -w '%{http_code}' -m 10 "${BASE}/health/liveness")" && [ "$code" = "200" ]; then
  pass "/health/liveness 200"
else
  fail "/health/liveness 返回 ${code:-无响应}"
fi

ready_body="$(curl -s -m 20 -w '\n%{http_code}' "${BASE}/health/readiness" 2>/dev/null)"
ready_code="$(echo "$ready_body" | tail -1)"
if [ "$ready_code" = "200" ]; then
  pass "/health/readiness 200"
else
  fail "/health/readiness 返回 ${ready_code:-无响应}"
  echo "$ready_body" | head -c 500
fi

# ── L3 基础设施层 ──────────────────────────────────────────────────────────
layer "L3 基础设施层"
# app→依赖 逐项状态（走应用自带探测，覆盖 mysql/pg/es/redis/neo4j/minio）
deps="$(curl -s -m 20 "${BASE}/health/dependencies" 2>/dev/null)"
if [ -n "$deps" ]; then
  echo "$deps" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for item in (d.get("data") or d).get("dependencies", []) if isinstance(d.get("data") or d, dict) else []:
    name = item.get("name"); st = item.get("status")
    mark = "\033[1;32m✓\033[0m" if st in ("ok", "up", "UP", "healthy") else "\033[1;31m✗\033[0m"
    print(f"  {mark} dep {name}={st}")
' 2>/dev/null || echo "  (依赖明细解析跳过)"
fi

# 独立直探（不依赖应用自检）
if "${COMPOSE[@]}" exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
  pass "redis-cli ping -> PONG（容器内直探）"
else
  fail "redis 容器内直探失败"
fi
if "${COMPOSE[@]}" exec -T mysql mysqladmin ping -h 127.0.0.1 --silent >/dev/null 2>&1; then
  pass "mysqladmin ping（容器内直探）"
else
  # 部分镜像 mysqladmin 需凭据；退化为 TCP 探测
  if "${COMPOSE[@]}" exec -T mysql bash -c 'exec 3<>/dev/tcp/127.0.0.1/3306' >/dev/null 2>&1; then
    pass "mysql 3306 TCP 可达（容器内直探）"
  else
    fail "mysql 容器内直探失败"
  fi
fi

# ── L4 业务链路层 ──────────────────────────────────────────────────────────
layer "L4 业务链路层"
ADMIN_USER="$(grep -E '^JWT_ADMIN_USERNAME=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"
ADMIN_PASS="$(grep -E '^JWT_ADMIN_PASSWORD=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"
if [ -z "${ADMIN_USER:-}" ] || [ -z "${ADMIN_PASS:-}" ]; then
  fail "未取到 JWT_ADMIN_USERNAME/PASSWORD，跳过业务链路验证"
else
  login="$(curl -s -m 20 -X POST "${BASE}/admin/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}" 2>/dev/null)"
  token="$(echo "$login" | json_get "d.get('data',{}).get('token','')" || true)"
  if [ -n "${token:-}" ]; then
    pass "管理员登录成功（签发 JWT）"
    biz_code="$(curl -s -o /tmp/_biz.json -w '%{http_code}' -m 30 -X POST "${BASE}/manage/document/page/query" \
      -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' \
      -d '{"pageNo":1,"pageSize":1}' 2>/dev/null)"
    if [ "$biz_code" = "200" ]; then
      total="$(json_get "d.get('data',{}).get('total','?')" < /tmp/_biz.json || true)"
      pass "业务读接口 /manage/document/page/query 200（total=${total:-?}）"
    else
      fail "业务读接口返回 ${biz_code:-无响应}"
      head -c 300 /tmp/_biz.json 2>/dev/null; echo
    fi
  else
    fail "管理员登录失败：$(echo "$login" | head -c 200)"
  fi
fi

# ── L5 监控层 ──────────────────────────────────────────────────────────────
layer "L5 监控层"
metrics="$(curl -s -m 15 "${BASE}/metrics" 2>/dev/null)"
if [ -n "$metrics" ]; then
  stagelines="$(echo "$metrics" | grep -c '^stage_duration_seconds' || true)"
  llmlines="$(echo "$metrics" | grep -c '^llm_' || true)"
  pass "/metrics 可访问（stage_duration_seconds 系列=${stagelines}，llm_* 系列=${llmlines}）"
else
  fail "/metrics 无响应"
fi

# ── 可观测性栈（可选）──────────────────────────────────────────────────────
if [ "$WITH_OBS" = 1 ]; then
  layer "可观测性栈（Langfuse）"
  lf_port="$(grep -E '^LANGFUSE_WEB_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2 || true)"
  lf_code="$(curl -s -o /dev/null -w '%{http_code}' -m 15 "http://localhost:${lf_port:-3000}/api/public/health" 2>/dev/null)"
  if [ "$lf_code" = "200" ]; then
    pass "Langfuse /api/public/health 200"
  else
    fail "Langfuse 健康检查返回 ${lf_code:-无响应}"
  fi
  lf_otlp="$(curl -s -o /dev/null -w '%{http_code}' -m 15 -X POST \
    "http://localhost:${lf_port:-3000}/api/public/otel/v1/traces" \
    -H 'Content-Type: application/json' -d '{}' 2>/dev/null)"
  # 401/415 说明端点存在且要求认证/合法 OTLP body（预期），5xx/000 才算异常
  if [ "$lf_otlp" = "401" ] || [ "$lf_otlp" = "415" ] || [ "$lf_otlp" = "200" ]; then
    pass "OTLP 端点可达（HTTP ${lf_otlp}，需 Basic auth）"
  else
    fail "OTLP 端点异常（HTTP ${lf_otlp:-无响应}）"
  fi
fi

# ── 汇总 ───────────────────────────────────────────────────────────────────
echo
if [ "$FAILED" -eq 0 ]; then
  printf '\033[1;32m全部验证通过\033[0m\n'
  exit 0
fi
printf '\033[1;31m验证失败：%d 项\033[0m\n' "$FAILED"
exit 1
