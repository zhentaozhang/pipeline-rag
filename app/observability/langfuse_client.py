"""Langfuse 客户端单例（惰性初始化 + shutdown flush）

设计要点：
- 进程内单例：Langfuse 内部有后台线程 + 批量上报队列，重复实例化会导致 trace 分散/重复。
- 惰性初始化：import 时不断连外部服务；enabled=False 时直接返回 None（灰度安全）。
- shutdown 必须 flush：后台批量上报在进程退出前 flush，否则丢 trace。
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

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
        # shutdown 会先 flush 队列再释放后台线程/资源（仅 flush 会残留线程）
        _client.shutdown()
        _client = None


def get_trace_url(trace_id: str) -> str | None:
    """返回 Langfuse trace 深链 URL（供自研 UI 跳转），未启用时返回 None。

    容器部署时 `LANGFUSE_HOST` 是服务名（如 http://langfuse-web:3000），浏览器不可达；
    若配置了 `LANGFUSE_PUBLIC_URL`（对外地址），则把 host 换为对外地址。
    """
    client = get_langfuse()
    if client is None:
        return None
    url = client.get_trace_url(trace_id=trace_id)
    if not url:
        return None
    public = get_settings().langfuse.public_url.strip()
    if public:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        pub = urlsplit(public)
        url = urlunsplit((pub.scheme, pub.netloc, parts.path, parts.query, parts.fragment))
    return url


def record_standalone_generation(
    name: str,
    *,
    model: str,
    input: Any = None,
    output: Any = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:
    """离线进程（Celery）里为一次 LLM 调用创建独立 Langfuse trace + generation。

    离线任务不属于任何在线 exchange 的 trace，因此各自开一条独立 trace。
    """
    client = get_langfuse()
    if client is None:
        return

    from app.config import get_settings
    from app.observability.cost import estimate_cost

    trace_id = client.create_trace_id()
    gen = client.start_observation(
        trace_context={"trace_id": trace_id},
        name=name,
        as_type="generation",
        model=model,
        input=input,
        metadata=metadata,
    )
    total = prompt_tokens + completion_tokens
    cost = estimate_cost(
        model,
        prompt_tokens,
        completion_tokens,
        cache_hit_factor=get_settings().llm.cache_hit_price_factor,
    )
    gen.update(
        output=output,
        usage_details={"input": prompt_tokens, "output": completion_tokens, "total": total},
        cost_details={"total": cost},
    )
    gen.end()
