from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from openai import AsyncOpenAI

from app.config import get_settings
from app.infra.circuit_breaker import CircuitBreakerConfig, CircuitBreakerRegistry

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── 熔断器 ──────────────────────────────────────────────────────────────────

_llm_breaker = CircuitBreakerRegistry.get_or_register(
    "llm",
    CircuitBreakerConfig(
        name="llm",
        failure_threshold=settings.circuit_breaker.llm_failure_threshold,
        recovery_timeout=settings.circuit_breaker.llm_recovery_timeout,
        timeout=settings.circuit_breaker.default_timeout,
    ),
)


@asynccontextmanager
async def llm_breaker() -> AsyncIterator[None]:
    async with _llm_breaker:
        yield


# ── 共享客户端单例 ──────────────────────────────────────────────────────────

_chat_client: AsyncOpenAI | None = None
_embedding_client: AsyncOpenAI | None = None
_eval_client: AsyncOpenAI | None = None


def get_chat_client() -> AsyncOpenAI:
    global _chat_client
    if _chat_client is None:
        _chat_client = AsyncOpenAI(
            base_url=settings.llm.base_url,
            api_key=settings.llm.api_key,
            timeout=settings.llm.timeout_seconds,
        )
        logger.info("chat client created", base_url=settings.llm.base_url)
    return _chat_client


def get_embedding_client() -> AsyncOpenAI:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AsyncOpenAI(
            base_url=settings.llm.embedding_base_url or settings.llm.base_url,
            api_key=settings.llm.embedding_api_key or settings.llm.api_key,
            timeout=settings.llm.timeout_seconds,
        )
        logger.info(
            "embedding client created",
            base_url=settings.llm.embedding_base_url or settings.llm.base_url,
        )
    return _embedding_client


def get_eval_client() -> AsyncOpenAI:
    global _eval_client
    if _eval_client is not None:
        return _eval_client
    eval_base = settings.rag.evaluation_base_url or settings.llm.base_url
    eval_key = settings.rag.evaluation_api_key or settings.llm.api_key
    if eval_base == settings.llm.base_url and eval_key == settings.llm.api_key:
        _eval_client = get_chat_client()
    else:
        _eval_client = AsyncOpenAI(
            base_url=eval_base,
            api_key=eval_key,
            timeout=settings.rag.evaluation_timeout_seconds,
        )
        logger.info("eval client created", base_url=eval_base)
    return _eval_client


# ── LangChain ChatOpenAI 工厂 ───────────────────────────────────────────────

_LANGCHAIN_INIT: bool = False
_langchain_chat_model: Any = None


def get_langchain_chat_model() -> Any:
    """LangGraph 专用，内置 DashScope 兼容。惰性导入避免启动时加载 langchain。"""
    global _langchain_chat_model, _LANGCHAIN_INIT
    if _LANGCHAIN_INIT:
        return _langchain_chat_model
    _LANGCHAIN_INIT = True

    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    from app.chat.support import is_dashscope_provider, resolve_provider

    provider = resolve_provider(settings.llm.base_url)
    model_kwargs: dict[str, Any] = {}
    if is_dashscope_provider(provider):
        model_kwargs["parallel_tool_calls"] = False
        model_kwargs["stream_usage"] = False
        logger.info("DashScope 兼容模式已启用: parallel_tool_calls=False, stream_usage=False")
    else:
        model_kwargs["parallel_tool_calls"] = True

    _langchain_chat_model = ChatOpenAI(
        model=settings.llm.model,
        api_key=SecretStr(settings.llm.api_key),
        base_url=settings.llm.base_url,
        **model_kwargs,
    )
    return _langchain_chat_model
