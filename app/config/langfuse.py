from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class LangfuseSettings(BaseSettings):
    """Langfuse 可观测平台配置（LLM/RAG trace + 评估后端）"""

    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    # 空串 = 使用 Langfuse Cloud 默认；自建时填 http://localhost:3000
    host: str = ""
    # 浏览器可达的对外地址（深链用）。容器内 host 为服务名（如 http://langfuse-web:3000）
    # 时，深链需用对外地址（如 http://localhost:3000）。
    public_url: str = ""
    sample_rate: float = 1.0
    flush_at: int = 15
    flush_interval: float = 0.5
    release: str | None = None
    # 上报到 Langfuse 的 input/output 最大字符数（0=不限）。超出部分截断，避免全量明文。
    max_io_chars: int = 4000

    model_config = SettingsConfigDict(env_prefix="LANGFUSE_", env_file=_ENV_FILE, extra="ignore")
