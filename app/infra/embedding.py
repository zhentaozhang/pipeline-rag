"""
Embedding 提供者抽象层
支持多种嵌入服务，通过配置切换提供者类型。
"""

from abc import ABC, abstractmethod
from typing import Any, cast

import httpx
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

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self._client = client or get_embedding_client()
        self._model = model or get_settings().llm.embedding_model
        self._dim = dimensions or get_settings().llm.embedding_dimensions
        self._dim_checked = False

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with _embed_breaker:
            response = await self._client.embeddings.create(
                input=texts,
                model=self._model,
            )
        embeddings = [data.embedding for data in response.data]
        if embeddings and not self._dim_checked:
            actual_dim = len(embeddings[0])
            if actual_dim != self._dim:
                logger.warning(
                    "embedding dimensions mismatch",
                    expected=self._dim,
                    actual=actual_dim,
                    model=self._model,
                    hint="Ensure get_settings().llm.embedding_dimensions matches the model dimension, otherwise PGVector insert will fail",
                )
            self._dim_checked = True
        return embeddings

    def dimensions(self) -> int:
        return self._dim


class OllamaEmbeddingProvider(EmbeddingProvider):
    """本地 Ollama 嵌入服务 (支持 /api/embed 和 /api/embeddings)"""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        raw_url = (
            base_url or get_settings().llm.embedding_base_url or "http://localhost:11434"
        ).rstrip("/")
        if raw_url.endswith("/v1"):
            raw_url = raw_url[:-3].rstrip("/")
        self._base_url = raw_url
        self._model = model or get_settings().llm.embedding_model
        self._dim = dimensions or get_settings().llm.embedding_dimensions
        self._dim_checked = False
        self._client = httpx.AsyncClient(timeout=float(get_settings().llm.timeout_seconds))

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with _embed_breaker:
            # 优先尝试 Ollama 现代批量接口 /api/embed
            try:
                resp = await self._client.post(
                    f"{self._base_url}/api/embed",
                    json={"model": self._model, "input": texts},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings:
                        self._validate_dimensions(embeddings)
                        return cast(list[list[float]], embeddings)
            except Exception as e:
                logger.debug("ollama /api/embed failed, trying fallback", error=str(e))

            # 降级尝试 Ollama 单条接口 /api/embeddings 逐条生成
            results: list[list[float]] = []
            for t in texts:
                resp = await self._client.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": self._model, "prompt": t},
                )
                resp.raise_for_status()
                data = resp.json()
                results.append(data.get("embedding", []))

            if results:
                self._validate_dimensions(results)
            return results

    def _validate_dimensions(self, embeddings: list[list[float]]) -> None:
        if embeddings and not self._dim_checked:
            actual_dim = len(embeddings[0])
            if actual_dim != self._dim:
                logger.warning(
                    "ollama embedding dimensions mismatch",
                    expected=self._dim,
                    actual=actual_dim,
                    model=self._model,
                    hint="Ensure get_settings().llm.embedding_dimensions matches the model dimension",
                )
            self._dim_checked = True

    def dimensions(self) -> int:
        return self._dim

    async def aclose(self) -> None:
        await self._client.aclose()


class LocalTEIEmbeddingProvider(EmbeddingProvider):
    """本地 Hugging Face Text Embeddings Inference (TEI) 或本地端点"""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        dimensions: int | None = None,
        api_key: str | None = None,
    ) -> None:
        raw_url = (
            base_url or get_settings().llm.embedding_base_url or "http://localhost:8080"
        ).rstrip("/")
        if raw_url.endswith("/v1"):
            raw_url = raw_url[:-3].rstrip("/")
        self._base_url = raw_url
        self._model = model or get_settings().llm.embedding_model
        self._dim = dimensions or get_settings().llm.embedding_dimensions
        self._api_key = api_key or get_settings().llm.embedding_api_key or "EMPTY"
        self._dim_checked = False
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        self._client = httpx.AsyncClient(
            headers=headers, timeout=float(get_settings().llm.timeout_seconds)
        )

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        async with _embed_breaker:
            # 1. 优先尝试 TEI 原生 /embed 接口
            try:
                resp = await self._client.post(
                    f"{self._base_url}/embed",
                    json={"inputs": texts, "truncate": True},
                )
                if resp.status_code == 200:
                    embeddings = resp.json()
                    if isinstance(embeddings, list) and (
                        not embeddings or isinstance(embeddings[0], list)
                    ):
                        self._validate_dimensions(embeddings)
                        return embeddings
            except Exception as e:
                logger.debug("tei /embed failed, trying /v1/embeddings", error=str(e))

            # 2. 降级尝试标准 OpenAI 兼容 /v1/embeddings
            resp = await self._client.post(
                f"{self._base_url}/v1/embeddings",
                json={"model": self._model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = [item["embedding"] for item in data.get("data", [])]
            if embeddings:
                self._validate_dimensions(embeddings)
            return embeddings

    def _validate_dimensions(self, embeddings: list[list[float]]) -> None:
        if embeddings and not self._dim_checked:
            actual_dim = len(embeddings[0])
            if actual_dim != self._dim:
                logger.warning(
                    "tei embedding dimensions mismatch",
                    expected=self._dim,
                    actual=actual_dim,
                    model=self._model,
                    hint="Ensure get_settings().llm.embedding_dimensions matches the model dimension",
                )
            self._dim_checked = True

    def dimensions(self) -> int:
        return self._dim

    async def aclose(self) -> None:
        await self._client.aclose()


_embedding_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """工厂方法：返回模块级单例（避免重复创建客户端）"""
    global _embedding_provider
    if _embedding_provider is not None:
        return _embedding_provider
    provider_type = (get_settings().llm.embedding_provider or "openai").lower()
    logger.info("embedding provider selected", provider=provider_type)
    if provider_type == "openai":
        _embedding_provider = OpenAIEmbeddingProvider()
        return _embedding_provider
    if provider_type == "ollama":
        _embedding_provider = OllamaEmbeddingProvider()
        return _embedding_provider
    if provider_type in ("tei", "local_tei", "local"):
        _embedding_provider = LocalTEIEmbeddingProvider()
        return _embedding_provider
    raise ValueError(f"Unsupported embedding provider: {provider_type}")


def reset_embedding_provider() -> None:
    """重置单例（主要用于测试）"""
    global _embedding_provider
    _embedding_provider = None
