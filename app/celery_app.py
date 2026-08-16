import asyncio
from typing import Any

import structlog
from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

logger = structlog.get_logger(__name__)


def make_celery() -> Celery:
    """创建并配置全局 Celery 实例"""
    s = get_settings()
    app = Celery(
        "pipeline_rag",
        broker=s.celery.broker_url,
        backend=s.celery.result_backend,
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Asia/Shanghai",
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        beat_schedule={
            "cleanup-orphan-documents": {
                "task": "document.cleanup_orphans",
                "schedule": crontab(hour=2, minute=0),
            },
            # P1-2: 索引对账——清理各存储孤儿文档（与 cleanup 互补：cleanup 补偿状态，reconcile 清理残留）
            "reconcile-indexes": {
                "task": "document.reconcile_indexes",
                "schedule": crontab(hour=3, minute=30),
            },
            # P3 事实记忆保留期清理（隐私数据生命周期）
            "prune-user-facts": {
                "task": "chat.prune_user_facts",
                "schedule": crontab(hour=4, minute=30),
            },
        },
    )
    return app


celery_app = make_celery()
# 自动发现并注册所有 celery task 模块
celery_app.autodiscover_tasks(["app.document", "app.chat"])

# 注册死信信号处理器（import 位置在 celery_app 创建之后，因 signal 绑定需要 celery_app 就绪）
import app.document.dlq  # noqa: E402, F401

# ── Worker 进程共享事件循环 ────────────────────────────────────────────────
# Celery prefork 每个子进程一个事件循环，只 stop 不 close，保证连接池中的
# aiomysql/asyncpg 连接始终绑定到同一个循环，避免 "Future attached to a
# different loop" 错误。

_worker_loop: asyncio.AbstractEventLoop | None = None


def _ensure_worker_loop() -> asyncio.AbstractEventLoop:
    """获取或创建 worker 进程的共享事件循环。"""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
    return _worker_loop


def run_async(coro: Any) -> Any:
    """在共享事件循环中运行协程，阻塞等待并返回结果。

    复用同一个事件循环，避免连接池 Future 跨循环失效。
    _ensure_worker_loop() 已兜底 is_closed() 重建，无需 try/except。
    """
    global _worker_loop
    loop = _ensure_worker_loop()
    return loop.run_until_complete(coro)
