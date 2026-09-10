from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class LangfuseSettings(BaseSettings):
    """Langfuse 可观测平台配置（LLM/RAG trace + 评估后端）"""

    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    # 空串 = 使用 Langfuse Cloud 默认；自建时填 http://localhost:3000
    host: str = ""
    sample_rate: float = 1.0
    flush_at: int = 15
    flush_interval: float = 0.5
    release: str | None = None

    model_config = SettingsConfigDict(env_prefix="LANGFUSE_", env_file=_ENV_FILE, extra="ignore")
