#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

echo "============================================"
echo "  离线回归评估流水线"
echo "============================================"

# Step 1: Ensure Docker services are running
echo ""
echo "[1/3] 检查 Docker 服务..."
docker compose up -d mysql postgres redis elasticsearch 2>/dev/null || true

until docker compose exec -T mysql mysqladmin ping -h localhost --silent 2>/dev/null; do
  echo "  Waiting for MySQL..."
  sleep 2
done
echo "  ✅ MySQL ready"

until docker compose exec -T postgres pg_isready -U postgres --quiet 2>/dev/null; do
  echo "  Waiting for Postgres..."
  sleep 2
done
echo "  ✅ Postgres ready"

until docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; do
  echo "  Waiting for Redis..."
  sleep 1
done
echo "  ✅ Redis ready"

# Step 2: Run Alembic migrations
echo ""
echo "[2/3] 运行数据库迁移..."
uv run alembic upgrade head
echo "  ✅ Migrations complete"

# Step 3: Run evaluation CLI
echo ""
echo "[3/3] 启动离线评估..."
echo ""

uv run python -m app.evaluation.cli list
echo ""
uv run python -m app.evaluation.cli run 2
