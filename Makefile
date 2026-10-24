# pipeline-rag 常用操作（后端与前端分开部署）
#
# 全部目标均为对 docker compose / 现有脚本的薄封装，不重复实现逻辑。
SHELL := /bin/bash

BACKEND_COMPOSE  := docker compose -f docker-compose.yml
OBS_COMPOSE      := docker compose -f docker-compose.yml -f docker-compose.observability.yml --profile observability
FRONTEND_COMPOSE := docker compose -f docker-compose.frontend.yml

.DEFAULT_GOAL := help

.PHONY: help init build up up-obs down down-all restart logs ps shell migrate verify test test-integration \
        lint format format-check typecheck check hooks config-check eval-ab \
        obs-up obs-down obs-logs \
        jev-up jev-logs jev-lock \
        fe-build fe-up fe-down fe-restart fe-logs fe-lint fe-test \
        up-all clean reset

help: ## 显示所有可用命令
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

init: ## 首次：从模板生成 .env（已存在则不覆盖）
	@test -f .env || (cp .env.example .env && echo "已生成 .env，请填写密钥后再执行 make up")
	@test -f .env && echo ".env 就绪"

# ── 质量门禁与测试 ──────────────────────────────────────────────────────────
lint: ## 代码风格与规范检查 (ruff check)
	uv run ruff check .

format: ## 自动格式化代码 (ruff format)
	uv run ruff format .

format-check: ## 代码格式校验 (ruff format --check)
	uv run ruff format --check .

typecheck: ## 静态类型检查 (mypy)
	uv run mypy app

test: ## 运行单元测试
	uv run pytest tests/unit -q

test-integration: ## 运行集成测试（需要本地数据库环境就绪）
	uv run pytest tests/integration -q

check: lint format-check typecheck test ## 本地全量质量门禁（推代码前必跑）

# 与 CI 同一套 pin：ruff/mypy 版本取自 uv.lock 与 .pre-commit-config.yaml，
# 装了 hook 之后提交时跑 ruff/mypy，推送时额外跑快速用例，避免"本地绿 / CI 红"。
hooks: ## 安装 git hooks（pre-commit + pre-push，与 CI 同源）
	@if [ -n "$$(git config --get core.hooksPath)" ]; then \
		echo "core.hooksPath 已设置为 '$$(git config --get core.hooksPath)'，pre-commit 会拒绝安装。"; \
		echo "若该路径已失效（例如指向被删除的目录），先执行： git config --unset core.hooksPath"; \
		exit 1; \
	fi
	uv run pre-commit install --install-hooks
	uv run pre-commit install --hook-type pre-push

eval-gate: ## 检索回归门禁（chunk_id 口径 R@5；不含 LLM judge）
	uv run python -m scripts.evaluation.runner --round gate --retrieval-only --no-rewrite \
		--channels both --gold-file reports/gold_llm.json --min-recall-ids 0.90

eval-ab: ## JEV 决策 A/B 门禁（--require-jev：服务不可达即失败，不再静默通过）
	uv run python -m scripts.evaluation.decision_ab --all --backends jev \
		--min-recall 0.8 --min-precision 0.85 --min-f1 0.8 \
		--min-accuracy 0.75 --min-macro-f1 0.75 --require-jev

config-check: ## 校验全部 Docker Compose 配置文件语法
	@$(BACKEND_COMPOSE) config >/dev/null && echo "✓ docker-compose.yml OK"
	@$(FRONTEND_COMPOSE) config >/dev/null && echo "✓ docker-compose.frontend.yml OK"
	@$(OBS_COMPOSE) config >/dev/null && echo "✓ docker-compose.observability.yml OK"
	@docker compose -f docker-compose.yml -f docker-compose.override.yml config >/dev/null && echo "✓ docker-compose.override.yml OK"

# ── 后端 ────────────────────────────────────────────────────────────────────
build: ## 构建全部后端业务镜像 (app, jev, elasticsearch)
	$(BACKEND_COMPOSE) build

up: ## 启动后端栈（幂等；等价 ./bin/deploy.sh）
	./bin/deploy.sh

up-obs: ## 启动后端栈 + Langfuse 可观测性
	./bin/deploy.sh --with-observability

jev-up: ## 构建并启动 JEV 决策服务（含开发 override）
	$(BACKEND_COMPOSE) -f docker-compose.override.yml up -d --build jev-service

jev-logs: ## 跟踪 JEV 决策服务日志
	$(BACKEND_COMPOSE) logs -f --tail=100 jev-service

# jev_service 不是 uv 项目（无 pyproject/uv.lock），依赖靠 requirements.txt + 冻结锁。
# 锁按 linux/x86_64 目标平台解析（镜像内的真实平台），改依赖后必须重新生成。
jev-lock: ## 重新生成 jev_service/requirements.lock.txt
	uv pip compile --python-platform x86_64-unknown-linux-gnu \
		jev_service/requirements.txt -o jev_service/requirements.lock.txt

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

fe-lint: ## 前端代码规范检查 (eslint)
	cd frontend && npm run lint

fe-test: ## 前端单元测试 (vitest)
	cd frontend && npm test

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
