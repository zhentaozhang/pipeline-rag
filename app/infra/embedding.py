"""
Embedding 提供者抽象层
支持多种嵌入服务，通过配置切换提供者类型。
"""

from abc import ABC, abstractmethod

import structlog

from app.common.llm_client import get_embedding_client
from app.config import get_settings
from app.infra.circuit_breaker import CircuitBreakerConfig, CircuitBreakerRegistry

logger = structlog.get_logger(__name__)
settings = get_settings()

_embed_breaker = CircuitBreakerRegistry.get_or_register(
    "embedding",
    CircuitBreakerConfig(
        name="embedding",
        failure_threshold=settings.circuit_breaker.llm_failure_threshold,
        recovery_timeout=settings.circuit_breaker.llm_recovery_timeout,
        timeout=settings.circuit_breaker.default_timeout,
    ),
)


class EmbeddingProvider(ABC):
    """嵌入模型抽象接口"""

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def dimensions(self) -> int: ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI 兼容接口的嵌入服务"""

    def __init__(self) -> None:
        self._client = get_embedding_client()
        self._model = settings.llm.embedding_model
        self._dim = settings.llm.embedding_dimensions

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        async with _embed_breaker:
            response = await self._client.embeddings.create(
                input=texts,
                model=self._model,
            )
        return [data.embedding for data in response.data]

    def dimensions(self) -> int:
        return self._dim


_embedding_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """工厂方法：返回模块级单例（避免重复创建 AsyncOpenAI 客户端）"""
    global _embedding_provider
    if _embedding_provider is not None:
        return _embedding_provider
    provider_type = get_settings().llm.embedding_provider
    logger.info("embedding provider selected", provider=provider_type)
    if provider_type == "openai":
        _embedding_provider = OpenAIEmbeddingProvider()
        return _embedding_provider
    raise ValueError(f"Unsupported embedding provider: {provider_type}")
