from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class AppSettings(BaseSettings):
    """FastAPI 应用基础配置"""

    env: Literal["development", "production", "testing"] = "development"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    api_key: str = ""
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=_ENV_FILE, extra="ignore")


class PreviewModeSettings(BaseSettings):
    """线上演示只读模式"""

    enabled: bool = False
    message: str = "当前环境为只读展示模式，仅开放浏览与检索能力"

    model_config = SettingsConfigDict(env_prefix="PREVIEW_", env_file=_ENV_FILE, extra="ignore")
