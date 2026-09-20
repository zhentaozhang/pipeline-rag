# pipeline-rag 常用操作（后端与前端分开部署）
#
# 全部目标均为对 docker compose / 现有脚本的薄封装，不重复实现逻辑。
SHELL := /bin/bash

BACKEND_COMPOSE  := docker compose -f docker-compose.yml
OBS_COMPOSE      := docker compose -f docker-compose.yml -f docker-compose.observability.yml --profile observability
FRONTEND_COMPOSE := docker compose -f docker-compose.frontend.yml

.DEFAULT_GOAL := help

.PHONY: help init build up up-obs down down-all restart logs ps shell migrate verify test \
        obs-up obs-down obs-logs \
        fe-build fe-up fe-down fe-restart fe-logs \
        up-all clean reset

help: ## 显示所有可用命令
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

init: ## 首次：从模板生成 .env（已存在则不覆盖）
	@test -f .env || (cp .env.example .env && echo "已生成 .env，请填写密钥后再执行 make up")
	@test -f .env && echo ".env 就绪"

# ── 后端 ────────────────────────────────────────────────────────────────────
build: ## 构建后端镜像
	$(BACKEND_COMPOSE) build app

up: ## 启动后端栈（幂等；等价 ./bin/deploy.sh）
	./bin/deploy.sh

up-obs: ## 启动后端栈 + Langfuse 可观测性
	./bin/deploy.sh --with-observability

down: ## 停止后端栈（保留数据卷）
	$(BACKEND_COMPOSE) down --remove-orphans

down-all: ## 停止后端栈 + 可观测性栈
	$(OBS_COMPOSE) down --remove-orphans || true

restart: ## 重启后端 app
	$(BACKEND_COMPOSE) restart app

logs: ## 跟踪后端全部日志
	$(BACKEND_COMPOSE) logs -f --tail=100

ps: ## 查看后端容器状态
	$(BACKEND_COMPOSE) ps

shell: ## 进入 app 容器
	$(BACKEND_COMPOSE) exec app bash

migrate: ## 手动执行数据库迁移（alembic upgrade head）
	$(BACKEND_COMPOSE) run --rm migrate

verify: ## 后端分层验证（L1-L5）
	./bin/verify-deploy.sh

test: ## 运行单元测试
	uv run pytest -q

# ── 可观测性（Langfuse）────────────────────────────────────────────────────
obs-up: ## 仅启动可观测性栈
	$(OBS_COMPOSE) up -d

obs-down: ## 停止可观测性栈
	$(OBS_COMPOSE) down --remove-orphans

obs-logs: ## 跟踪可观测性栈日志
	$(OBS_COMPOSE) logs -f --tail=100

# ── 前端（独立部署）────────────────────────────────────────────────────────
fe-build: ## 构建前端镜像
	$(FRONTEND_COMPOSE) build

fe-up: ## 启动前端容器（自动重建）
	$(FRONTEND_COMPOSE) up -d --build

fe-down: ## 停止前端容器
	$(FRONTEND_COMPOSE) down --remove-orphans

fe-restart: ## 重启前端容器
	$(FRONTEND_COMPOSE) restart frontend

fe-logs: ## 跟踪前端日志
	$(FRONTEND_COMPOSE) logs -f --tail=100

# ── 组合 ────────────────────────────────────────────────────────────────────
up-all: up fe-up ## 启动后端 + 前端

clean: ## 停止全部容器（保留数据卷）
	$(FRONTEND_COMPOSE) down --remove-orphans || true
	$(OBS_COMPOSE) down --remove-orphans || true
	$(BACKEND_COMPOSE) down --remove-orphans || true

reset: ## ⚠️ 停止全部并删除数据卷（数据不可恢复）
	$(FRONTEND_COMPOSE) down --remove-orphans -v || true
	$(OBS_COMPOSE) down --remove-orphans -v || true
	$(BACKEND_COMPOSE) down --remove-orphans -v || true
