from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class LLMSettings(BaseSettings):
    """LLM 服务配置（OpenAI 兼容接口）"""

    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-v4-flash"
    temperature: float = 0.5
    max_tokens: int = 5000
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key: str = ""
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-v3"
    embedding_dimensions: int = 1536

    context_window_limit: int = 128000

    timeout_seconds: int = 60

    # Prompt Caching（P0）：缓存命中 input token 的单价折扣系数。
    # DeepSeek context caching 命中约 1/10 单价；OpenAI 自动缓存同理。
    cache_hit_price_factor: float = 0.1

    # 并发控制：进程级最大并发 LLM 调用数（信号量保护，防 429 与雪崩）
    max_concurrent_calls: int = 20

    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=_ENV_FILE, extra="ignore")


class TavilySettings(BaseSettings):
    """Tavily 联网搜索配置"""

    enabled: bool = True
    base_url: str = "https://api.tavily.com"
    search_path: str = "/search"
    api_key: str = ""
    topic: str = "general"
    search_depth: str = "advanced"
    max_results: int = 5
    include_answer: bool = True
    include_raw_content: bool = False
    connect_timeout_ms: int = 3000
    read_timeout_ms: int = 6000
    max_retries: int = 2
    retry_initial_delay_ms: int = 200
    retry_max_delay_ms: int = 1200

    model_config = SettingsConfigDict(env_prefix="TAVILY_", env_file=_ENV_FILE, extra="ignore")


class RerankSettings(BaseSettings):
    """Rerank 精排服务配置（可选）"""

    enabled: bool = False
    base_url: str = "https://api.siliconflow.cn/v1"
    api_key: str = ""
    model: str = "BAAI/bge-reranker-v2-m3"
    # top_n：请求体里"送打分条数"的语义（调用方恒传候选数，这里仅作兜底默认）
    top_n: int = 10
    # keep_top_n：本地保留条数；0 = 不截断（默认），避免静默封顶父块多样性
    keep_top_n: int = 0
    connect_timeout_ms: int = 3000
    read_timeout_ms: int = 6000
    inject_title_breadcrumbs: bool = True

    model_config = SettingsConfigDict(env_prefix="RERANK_", env_file=_ENV_FILE, extra="ignore")
