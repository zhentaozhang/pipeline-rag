"""Langfuse 客户端单例（惰性初始化 + shutdown flush）

设计要点：
- 进程内单例：Langfuse 内部有后台线程 + 批量上报队列，重复实例化会导致 trace 分散/重复。
- 惰性初始化：import 时不断连外部服务；enabled=False 时直接返回 None（灰度安全）。
- shutdown 必须 flush：后台批量上报在进程退出前 flush，否则丢 trace。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from langfuse import Langfuse

from app.config import get_settings

if TYPE_CHECKING:
    from app.config.langfuse import LangfuseSettings

_client: Langfuse | None = None
_lock = threading.Lock()


def _build_client(settings: LangfuseSettings) -> Langfuse:
    return Langfuse(
        public_key=settings.public_key,
        secret_key=settings.secret_key,
        host=settings.host or None,
        sample_rate=settings.sample_rate,
        flush_at=settings.flush_at,
        flush_interval=settings.flush_interval,
        release=settings.release,
    )


def get_langfuse() -> Langfuse | None:
    global _client
    settings = get_settings().langfuse
    if not settings.enabled:
        return None
    if _client is None:
        with _lock:
            if _client is None:
                _client = _build_client(settings)
    return _client


def shutdown_langfuse() -> None:
    global _client
    if _client is not None:
        _client.flush()
        _client = None


def get_trace_url(trace_id: str) -> str | None:
    """返回 Langfuse trace 深链 URL（供自研 UI 跳转），未启用时返回 None。"""
    client = get_langfuse()
    if client is None:
        return None
    return client.get_trace_url(trace_id=trace_id)
