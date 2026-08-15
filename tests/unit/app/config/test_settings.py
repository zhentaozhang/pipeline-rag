import pytest

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


class TestDBSettings:
    def test_mysql_urls(self):
        s = MySQLSettings(
            user="u", password="p", host="h", port=1234, db="d"
        )
        assert s.url == "mysql+aiomysql://u:p@h:1234/d"
        assert s.sync_url == "mysql+pymysql://u:p@h:1234/d"
        assert s.checkpoint_url == "mysql://u:p@h:1234/d"

    def test_postgres_urls(self):
        s = PostgresSettings(user="u", password="p", host="h", port=5432, db="d")
        assert s.url == "postgresql+asyncpg://u:p@h:5432/d"
        assert s.sync_url == "postgresql+psycopg2://u:p@h:5432/d"


class TestInfraSettings:
    def test_redis_url_without_password(self):
        s = RedisSettings(host="h", port=6379, db=3)
        assert s.url == "redis://h:6379/3"

    def test_redis_url_with_password(self):
        s = RedisSettings(host="h", port=6379, db=3, password="secret")
        assert s.url == "redis://:secret@h:6379/3"

    def test_es_base_url(self):
        s = ElasticsearchSettings(scheme="https", host="h", port=9201)
        assert s.base_url == "https://h:9201"

    def test_es_index_defaults(self):
        s = ElasticsearchSettings(_env_file=None)
        assert s.index_prefix == "pipeline_rag"
        assert s.keyword_index_name == "pipeline_rag_document_keyword"
        assert s.navigation_index_name == "pipeline_rag_document_navigation"
        assert s.route_index_name == "pipeline_rag_knowledge_route"

    def test_neo4j_defaults(self):
        s = Neo4jSettings()
        assert s.uri == "bolt://localhost:7687"
        assert s.database == "neo4j"
        assert s.query_timeout_seconds == 5

    def test_minio_defaults(self):
        s = MinIOSettings(_env_file=None)
        assert s.endpoint == "localhost:9000"
        assert s.bucket == "pipeline-rag-document"
        assert s.object_prefix == "rag/document"
        assert s.parsed_text_prefix == "rag/parsed-text"

    def test_otel_defaults(self):
        s = OTelSettings()
        assert not s.enabled
        assert s.service_name == "pipeline-rag"
        assert s.exporter_otlp_endpoint == "http://localhost:4317"


class TestLLMSettings:
    def test_env_prefix_override(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "override-model")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.9")
        s = LLMSettings()
        assert s.model == "override-model"
        assert s.temperature == 0.9

    def test_env_does_not_leak_into_defaults(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "override-model")
        s = LLMSettings(_env_file=None)
        assert s.max_tokens == 5000
        assert s.timeout_seconds == 60
        assert s.embedding_model == "text-embedding-v3"
        assert s.embedding_dimensions == 1536
        assert s.context_window_limit == 128000

    def test_tavily_defaults(self):
        s = TavilySettings()
        assert s.search_path == "/search"
        assert s.max_results == 5
        assert s.search_depth == "advanced"
        assert s.max_retries == 2

    def test_rerank_defaults(self):
        s = RerankSettings(_env_file=None)
        assert not s.enabled
        assert s.model == "BAAI/bge-reranker-v2-m3"
        assert s.top_n == 3


class TestPipelineSettings:
    def test_celery_defaults(self):
        s = CelerySettings()
        assert s.broker_url == "redis://localhost:6379/1"
        assert s.result_backend == "redis://localhost:6379/2"

    def test_rag_budget_defaults(self, monkeypatch):
        s = RAGSettings()
        assert s.prompt_budget_total == 5200
        assert s.prompt_budget_per_subquestion == 2200
        assert s.max_sub_questions == 4
        assert s.no_evidence_reply.startswith("当前没有")
        assert s.knowledge_route_confidence_threshold == 0.40
        assert s.checkpoint_keep_latest == 50
        assert s.evaluation_sample_rate == 0.0

    def test_agent_defaults(self):
        s = AgentSettings()
        assert s.max_model_calls_per_run == 8
        assert s.max_tool_calls_per_run == 6
        assert s.max_model_calls_per_session == 40
        assert s.max_tool_calls_per_session == 30

    def test_memory_defaults(self):
        s = MemorySettings()
        assert s.strategy == "summary_compression"
        assert s.window_size == 4
        assert s.max_summary_chars == 1400
        assert s.max_window_chars == 2200
        assert s.max_item_length == 80

    def test_chunk_defaults(self):
        s = ChunkSettings()
        assert s.recursive_max_chars == 800
        assert s.recursive_overlap_chars == 120
        assert s.semantic_max_chars == 700
        assert s.semantic_similarity_threshold == 0.18
        assert not s.llm_enabled

    def test_structure_defaults(self):
        s = StructureParsingSettings()
        assert s.max_plain_heading_chars == 32
        assert s.ambiguity_confidence_floor == 0.45
        assert s.ambiguity_confidence_ceil == 0.80
        assert s.max_ambiguous_signals_per_call == 8
        assert s.context_window_lines == 2

    def test_recommendation_defaults(self):
        s = RecommendationSettings()
        assert s.enabled
        assert s.timeout_ms == 3000

    def test_rate_limit_defaults(self):
        s = RateLimitSettings()
        assert s.chat_calls == 10
        assert s.chat_window_seconds == 60
        assert s.manage_calls == 60


class TestAppSettings:
    def test_defaults(self, monkeypatch):
        s = AppSettings()
        assert s.env == "development"
        assert s.port == 8080
        assert len(s.cors_origins) == 4
        assert "http://localhost:5173" in s.cors_origins

    def test_env_prefix_override(self, monkeypatch):
        monkeypatch.setenv("APP_DEBUG", "true")
        s = AppSettings()
        assert s.debug is True

    def test_preview_defaults(self):
        s = PreviewModeSettings()
        assert not s.enabled
        assert "只读展示" in s.message


class TestJWTSettings:
    def test_defaults_warn(self):
        with pytest.warns(UserWarning) as record:
            JWTSettings(
                secret_key="pipeline-rag-admin-token-secret-change-me",
                admin_password="admin123456",
            )
        assert len(record) >= 1

    def test_custom_no_warning(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            JWTSettings(
                secret_key="x" * 40,
                admin_password="custom-pass",
            )

    def test_fields(self):
        s = JWTSettings(
            secret_key="x" * 40,
            admin_password="custom-pass",
            algorithm="HS512",
            expire_minutes=30,
        )
        assert s.algorithm == "HS512"
        assert s.expire_minutes == 30
