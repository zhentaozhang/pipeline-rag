from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class OTelSettings(BaseSettings):
    """OpenTelemetry 可观测性配置"""

    enabled: bool = False
    service_name: str = "pipeline-rag"
    exporter_otlp_endpoint: str = "http://localhost:4317"

    model_config = SettingsConfigDict(env_prefix="OTEL_", env_file=_ENV_FILE, extra="ignore")


class RedisSettings(BaseSettings):
    """Redis 配置（缓存 + 分布式锁 + Celery Broker）"""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str = ""
    max_connections: int = 50
    lease_ttl_seconds: int = 30
    renew_interval_seconds: int = 10
    lease_check_interval: int = 30

    @computed_field
    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"

    model_config = SettingsConfigDict(env_prefix="REDIS_", env_file=_ENV_FILE, extra="ignore")


class ElasticsearchSettings(BaseSettings):
    """Elasticsearch 配置"""

    enabled: bool = True
    host: str = "localhost"
    port: int = 9200
    scheme: str = "http"
    user: str = "elastic"
    password: str = "elastic"
    index_prefix: str = "pipeline_rag"
    keyword_index_name: str = "pipeline_rag_document_keyword"
    navigation_index_name: str = "pipeline_rag_document_navigation"
    route_index_name: str = "pipeline_rag_knowledge_route"
    analyzer: str = "ik_max_word"
    search_analyzer: str = "ik_smart"
    connect_timeout_ms: int = 3000
    socket_timeout_ms: int = 5000
    max_retries: int = 3

    @computed_field  # type: ignore[misc]
    @property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    model_config = SettingsConfigDict(env_prefix="ES_", env_file=_ENV_FILE, extra="ignore")


class Neo4jSettings(BaseSettings):
    """Neo4j 配置（文档结构图谱）"""

    enabled: bool = False
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "neo4j"
    database: str = "neo4j"
    query_timeout_seconds: int = 5

    model_config = SettingsConfigDict(env_prefix="NEO4J_", env_file=_ENV_FILE, extra="ignore")


class MinIOSettings(BaseSettings):
    """MinIO 对象存储配置"""

    endpoint: str = "localhost:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin"
    bucket: str = "pipeline-rag-document"
    secure: bool = False
    object_prefix: str = "rag/document"
    parsed_text_prefix: str = "rag/parsed-text"

    model_config = SettingsConfigDict(env_prefix="MINIO_", env_file=_ENV_FILE, extra="ignore")
