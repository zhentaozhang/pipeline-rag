from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class CelerySettings(BaseSettings):
    """Celery 异步任务配置"""

    broker_url: str = "redis://localhost:6379/1"
    result_backend: str = "redis://localhost:6379/2"

    model_config = SettingsConfigDict(env_prefix="CELERY_", env_file=_ENV_FILE, extra="ignore")


class RAGSettings(BaseSettings):
    """RAG 检索参数"""

    enabled: bool = True
    vector_top_k: int = 5
    keyword_top_k: int = 5
    candidate_top_k: int = 6
    final_top_k: int = 5
    min_vector_similarity: float = 0.55
    keyword_score_ratio: float = 0.35
    context_window_safety_margin: float = 0.15
    prompt_budget_total: int = 5200
    prompt_budget_per_subquestion: int = 2200
    parent_evidence_max_chars: int = 2200
    planning_history_max_chars: int = 1600
    answer_history_max_chars: int = 1000
    channel_timeout_ms: int = 5000
    sub_question_timeout_ms: int = 12000
    keyword_channel_enabled: bool = True
    max_sub_questions: int = 4
    no_evidence_reply: str = "当前没有从已接入文档中检索到足够证据，暂时不能给出可靠结论。"
    stream_timeout_seconds: int = 600
    answer_system_prompt: str = ""
    rewrite_enabled: bool = True
    rewrite_history_turns: int = 4
    rewrite_temperature: float = 0.1
    rewrite_top_p: float = 0.3
    rewrite_thinking: bool = False
    evaluation_enabled: bool = True
    evaluation_model: str = ""
    evaluation_base_url: str = ""
    evaluation_api_key: str = ""
    evaluation_timeout_seconds: int = 30
    evaluation_sample_rate: float = 0.0
    evidence_min_score: float = 0.1
    rerank_min_score: float = 0.0
    knowledge_route_confidence_threshold: float = 0.40
    checkpoint_keep_latest: int = 50
    vectorize_batch_size: int = 10
    # P0-2: Contextual Chunking——embedding 文本附加文档名+章节路径（重索引后生效，可回退关闭）
    contextual_chunking_enabled: bool = True
    supervisor_enabled: bool = True
    # P0-1c: LLM 分解前规则预筛——仅复合/分析类/长问题触发分解，简单问题零 LLM 成本
    supervisor_rule_prefilter: bool = True
    supervisor_temperature: float = 0.1
    supervisor_max_review_retries: int = 2
    quality_enabled: bool = True
    quality_max_retries: int = 2
    quality_min_score: float = 7.0
    quality_model: str = ""
    corrective_retrieval_enabled: bool = True
    corrective_retrieval_max_rounds: int = 1

    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=_ENV_FILE, extra="ignore")


class AgentSettings(BaseSettings):
    """Agent 安全限制 + 系统提示词"""

    max_model_calls_per_run: int = 8
    max_tool_calls_per_run: int = 6
    max_model_calls_per_session: int = 40
    max_tool_calls_per_session: int = 30
    system_prompt: str = ""

    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=_ENV_FILE, extra="ignore")


class MemorySettings(BaseSettings):
    """会话记忆配置"""

    enabled: bool = True
    strategy: Literal["none", "sliding_window", "summary_compression"] = "summary_compression"
    window_size: int = 4
    max_summary_chars: int = 1400
    max_window_chars: int = 2200
    summary_batch_size: int = 6
    max_section_items: int = 6
    max_item_length: int = 80

    model_config = SettingsConfigDict(env_prefix="MEMORY_", env_file=_ENV_FILE, extra="ignore")


class ChunkSettings(BaseSettings):
    """文档分段参数"""

    recursive_max_chars: int = 800
    recursive_overlap_chars: int = 120
    semantic_max_chars: int = 700
    semantic_min_chars: int = 240
    semantic_similarity_threshold: float = 0.18
    llm_enabled: bool = False
    llm_max_chars: int = 3500
    recommend_llm_when_low_quality: bool = True

    model_config = SettingsConfigDict(env_prefix="CHUNK_", env_file=_ENV_FILE, extra="ignore")


class StructureParsingSettings(BaseSettings):
    """文档结构解析参数"""

    max_plain_heading_chars: int = 32
    llm_disambiguation_enabled: bool = True
    ambiguity_confidence_floor: float = 0.45
    ambiguity_confidence_ceil: float = 0.80
    max_ambiguous_signals_per_call: int = 8
    context_window_lines: int = 2

    model_config = SettingsConfigDict(env_prefix="STRUCTURE_", env_file=_ENV_FILE, extra="ignore")


class RecommendationSettings(BaseSettings):
    """推荐追问配置"""

    enabled: bool = True
    timeout_ms: int = 3000

    model_config = SettingsConfigDict(env_prefix="RECOMMEND_", env_file=_ENV_FILE, extra="ignore")


class S3ConnectorSettings(BaseSettings):
    """S3 数据源连接器（P3-3）：扫描 S3 bucket 并导入文档处理流水线"""

    enabled: bool = False
    endpoint: str = "https://s3.amazonaws.com"
    access_key: str = ""
    secret_key: str = ""
    bucket: str = ""
    prefix: str = ""  # 对象前缀过滤（如 "documents/rag/"）
    file_types: str = ".pdf,.docx,.doc,.txt,.md,.pptx,.xlsx"  # 逗号分隔扩展名
    batch_size: int = 10
    temp_dir: str = "/tmp/rag-connector-s3"

    model_config = SettingsConfigDict(env_prefix="CONNECTOR_S3_", env_file=_ENV_FILE, extra="ignore")


class WebConnectorSettings(BaseSettings):
    """网页爬虫连接器（P3-3）：抓取公开站点内容导入文档流水线"""

    enabled: bool = False
    seed_urls: str = ""  # 逗号分隔种子页（无 sitemap 时从此递归发现）
    sitemap_url: str = ""  # sitemap.xml 地址（企业站标配，优先）
    max_pages: int = 50
    max_depth: int = 2  # 种子递归抓取深度
    concurrency: int = 4
    delay_seconds: float = 0.5  # 请求间隔，避免对目标站点造成压力
    respect_robots: bool = True
    user_agent: str = ""

    model_config = SettingsConfigDict(env_prefix="CONNECTOR_WEB_", env_file=_ENV_FILE, extra="ignore")


class MinerUSettings(BaseSettings):
    """MinerU 文档解析增强通道（P2-4）：复杂版式（扫描件/表格/多栏）走 MinerU，失败降级 unstructured"""

    enabled: bool = False
    base_url: str = "https://mineru.net"
    api_key: str = ""
    mode: str = "agent"  # agent（免 token，≤10MB/20页）| extract（需 token，≤200MB/200页）
    timeout_seconds: int = 60
    poll_interval_seconds: int = 2
    max_poll_retries: int = 30

    model_config = SettingsConfigDict(env_prefix="MINERU_", env_file=_ENV_FILE, extra="ignore")


class RateLimitSettings(BaseSettings):
    """Redis 滑动窗口限流配置"""

    enabled: bool = True
    chat_calls: int = 10
    chat_window_seconds: int = 60
    auth_calls: int = 20
    auth_window_seconds: int = 60
    manage_calls: int = 60
    manage_window_seconds: int = 60
    # 信任的反向代理层数。0 = 不信任 X-Forwarded-For（防伪造）；
    # 直连部署保持 0；有 N 层可信反代时设为 N，将从 XFF 右侧数第 N+1 个地址作为客户端。
    trust_proxy_count: int = 0

    model_config = SettingsConfigDict(env_prefix="RATE_LIMIT_", env_file=_ENV_FILE, extra="ignore")
