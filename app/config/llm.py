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
    top_n: int = 3
    connect_timeout_ms: int = 3000
    read_timeout_ms: int = 6000

    model_config = SettingsConfigDict(env_prefix="RERANK_", env_file=_ENV_FILE, extra="ignore")
