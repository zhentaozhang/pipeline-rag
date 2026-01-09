import warnings

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class JWTSettings(BaseSettings):
    """JWT 认证配置"""

    secret_key: str = "pipeline-rag-admin-token-secret-change-me"
    algorithm: str = "HS256"
    expire_minutes: int = 480
    admin_username: str = "admin"
    admin_password: str = "admin123456"

    def model_post_init(self, __context) -> None:
        if self.secret_key == "pipeline-rag-admin-token-secret-change-me":
            warnings.warn(
                "JWT secret_key 使用默认值，生产中请通过 JWT_SECRET_KEY 环境变量设置",
                stacklevel=2,
            )
        if self.admin_password == "admin123456":
            warnings.warn(
                "JWT admin_password 使用默认值，生产中请通过 JWT_ADMIN_PASSWORD 环境变量设置",
                stacklevel=2,
            )

    model_config = SettingsConfigDict(env_prefix="JWT_", env_file=_ENV_FILE, extra="ignore")
