import pytest

from app.config.app import AppSettings, PreviewModeSettings
from app.config.db import MySQLSettings, PostgresSettings
from app.config.infra import (
    ElasticsearchSettings,
    MinIOSettings,
    Neo4jSettings,
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
        s = MySQLSettings(user="u", password="p", host="h", port=1234, db="d")
        assert s.url == "mysql+aiomysql://u:p@h:1234/d"
        assert s.sync_url == "mysql+pymysql://u:p@h:1234/d"

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
        # top_n 既是 API 侧截断也是本地截断；小于 final_top_k 会把候选硬砍掉
        assert s.top_n == 10


class TestPipelineSettings:
    def test_celery_defaults(self):
        s = CelerySettings()
        assert s.broker_url == "redis://localhost:6379/1"
        assert s.result_backend == "redis://localhost:6379/2"

    def test_rag_budget_defaults(self, monkeypatch):
        s = RAGSettings(_env_file=None)
        # 与 .env / .env.example 的运行真值同源（此前代码默认 5200/2200 与实际部署背离）
        assert s.prompt_budget_total == 20000
        assert s.prompt_budget_per_subquestion == 8000
        assert s.parent_evidence_max_chars == 4000
        assert s.max_sub_questions == 4
        assert s.no_evidence_reply.startswith("当前没有")
        assert s.knowledge_route_confidence_threshold == 0.40
        assert s.evaluation_sample_rate == 0.0

    def test_rag_retrieval_defaults_match_measured_best(self, monkeypatch):
        """默认值必须等于 85 题实测最优配置，避免代码默认与 .env 长期背离。

        reports/ 实测（85 题，retrieval-only）：
          rerank 阈值 0.35 → Recall@5 0.7333；阈值关闭 → 0.8020
          multi-hop 拆分 → Recall@5 0.7133；不拆分 → 0.7267
        """
        s = RAGSettings(_env_file=None)
        assert s.rerank_relative_ratio == 0.0
        assert s.rerank_min_score == 0.0
        assert s.multi_hop_split_enabled is False

    def test_final_top_k_matches_the_measured_truncation_sweet_spot(self):
        """组席宽度必须覆盖证据缺口：k 8→16 多召回 8 题（McNemar p=0.0078）。

        reports/det_a.json（k=8）→ reports/trunc_k12.json / reports/trunc_k16.json：
          R@final_k_ids 0.8831 → 0.9173（k=12）→ 0.9462（k=16）
          R@5_ids / MRR_ids 不动 → 加宽只补尾部，不破坏头部排序
          预算侧无压力：20 块父块也只有 ~5.5k 字符，低于 prompt_budget_total=20000
        """
        s = RAGSettings(_env_file=None)
        assert s.final_top_k == 16

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
        assert s.enabled is False  # 017 决策：默认关（省 ~2s/轮）
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


class TestParentRerankDefaults:
    def test_parent_rerank_on_with_head_only(self):
        """父块级重排默认开：排序质量显著改善，且只重排头部以控制延迟。

        reports/trunc_k16.json（关闭）vs pr08_k16.json（top_n=8，均为 85 题 retrieval-only）：
          MRR_ids 0.8170 → 0.8428（+2.57pp，CI[0.68,5.10]pp，显著）
          nDCG@5_ids 0.8018 → 0.8210（显著）
          R@final_k_ids 0.9462 → 0.9462（不变）
          检索 p50 742ms → 939ms
        top_n=20 与 =8 效果相同但更慢；top_n=50 显著变差。
        """
        s = RAGSettings(_env_file=None)
        assert s.parent_rerank_enabled is True
        assert s.parent_rerank_top_n == 8
        assert s.parent_rerank_max_chars == 2000
        assert s.parent_rerank_blend == 1.0
