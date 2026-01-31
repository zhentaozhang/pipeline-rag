"""
Celery Worker 入口
启动命令：uv run celery -A worker.celery_app worker --loglevel=info --concurrency=4
"""

from app.document.tasks import celery_app  # noqa: F401 — 触发任务注册

if __name__ == "__main__":
    celery_app.start()
