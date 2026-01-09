"""Pipeline RAG Python — 配置包

Settings 聚合所有子域配置，通过 get_settings() 获取全局单例。
各子域 Settings 在 app/config/ 下按领域分文件存放。
"""

import logging
from functools import lru_cache

from app.config.app import AppSettings, PreviewModeSettings
from app.config.db import MySQLSettings, PostgresSettings
from app.config.infra import (
    ElasticsearchSettings,
    MinIOSettings,
    Neo4jSettings,
    OTelSettings,
    RedisSettings,
)
from app.config.llm import LLMSettings, RerankSettings, TavilySettings
from app.config.pipeline import (
    AgentSettings,
    CelerySettings,
    ChunkSettings,
    MemorySettings,
    RAGSettings,
    RateLimitSettings,
    RecommendationSettings,
    StructureParsingSettings,
)
from app.config.security import JWTSettings
from app.observability.settings import ObservabilitySettings
from app.safety.config import CircuitBreakerSettings, SafetySettings

logger = logging.getLogger(__name__)


class Settings:
    """全局配置单例，通过 get_settings() 获取"""

    def __init__(self) -> None:
        self.app: AppSettings = AppSettings()  # type: ignore[call-arg]
        self.mysql: MySQLSettings = MySQLSettings()  # type: ignore[call-arg]
        self.postgres: PostgresSettings = PostgresSettings()  # type: ignore[call-arg]
        self.otel: OTelSettings = OTelSettings()  # type: ignore[call-arg]
        self.redis: RedisSettings = RedisSettings()  # type: ignore[call-arg]
        self.es: ElasticsearchSettings = ElasticsearchSettings()  # type: ignore[call-arg]
        self.neo4j: Neo4jSettings = Neo4jSettings()  # type: ignore[call-arg]
        self.minio: MinIOSettings = MinIOSettings()  # type: ignore[call-arg]
        self.llm: LLMSettings = LLMSettings()  # type: ignore[call-arg]
        self.tavily: TavilySettings = TavilySettings()  # type: ignore[call-arg]
        self.rerank: RerankSettings = RerankSettings()  # type: ignore[call-arg]
        self.jwt: JWTSettings = JWTSettings()  # type: ignore[call-arg]
        self.celery: CelerySettings = CelerySettings()  # type: ignore[call-arg]
        self.rag: RAGSettings = RAGSettings()  # type: ignore[call-arg]
        self.agent: AgentSettings = AgentSettings()  # type: ignore[call-arg]
        self.memory: MemorySettings = MemorySettings()  # type: ignore[call-arg]
        self.structure: StructureParsingSettings = StructureParsingSettings()  # type: ignore[call-arg]
        self.preview: PreviewModeSettings = PreviewModeSettings()  # type: ignore[call-arg]
        self.chunk: ChunkSettings = ChunkSettings()  # type: ignore[call-arg]
        self.safety: SafetySettings = SafetySettings()  # type: ignore[call-arg]
        self.circuit_breaker: CircuitBreakerSettings = CircuitBreakerSettings()  # type: ignore[call-arg]
        self.recommendation: RecommendationSettings = RecommendationSettings()  # type: ignore[call-arg]
        self.rate_limit: RateLimitSettings = RateLimitSettings()  # type: ignore[call-arg]
        self.observability: ObservabilitySettings = ObservabilitySettings()  # type: ignore[call-arg]
        self._check_default_credentials()

    _KNOWN_DEFAULT_CREDENTIALS = {
        "5656",
        "elastic",
        "neo4j",
        "minioadmin",
        "pipeline-rag-admin-token-secret-change-me",
        "admin123456",
    }

    def _check_default_credentials(self) -> None:
        logging.basicConfig(level=logging.WARNING)
        checks = {
            "MySQL password": self.mysql.password,
            "Postgres password": self.postgres.password,
            "Elasticsearch password": self.es.password,
            "Neo4j password": self.neo4j.password,
            "MinIO access key": self.minio.access_key,
            "MinIO secret key": self.minio.secret_key,
            "JWT secret key": self.jwt.secret_key,
            "Admin password": self.jwt.admin_password,
        }
        for name, value in checks.items():
            if value in self._KNOWN_DEFAULT_CREDENTIALS:
                logger.warning(
                    "⚠️ %s using default value, production deployment must override via environment variable",
                    name,
                )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回全局唯一配置实例（lru_cache 保证单例）"""
    return Settings()
