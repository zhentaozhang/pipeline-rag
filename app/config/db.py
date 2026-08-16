from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.base import _ENV_FILE


class MySQLSettings(BaseSettings):
    """MySQL 配置（业务数据库）"""

    host: str = "localhost"
    port: int = 3306
    db: str = "pipeline_rag"
    user: str = "root"
    password: str = "5656"
    pool_size: int = 10
    max_overflow: int = 20
    slow_query_ms: int = 500  # 第三轮 #6：慢查询告警阈值（db 事件监听）

    @computed_field  # type: ignore[misc]
    @property
    def url(self) -> str:
        return f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    @computed_field  # type: ignore[misc]
    @property
    def sync_url(self) -> str:
        return f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    model_config = SettingsConfigDict(env_prefix="MYSQL_", env_file=_ENV_FILE, extra="ignore")


class PostgresSettings(BaseSettings):
    """PostgreSQL + PGVector 配置"""

    hnsw_index_enabled: bool = True  # 第三轮 #1：embedding 列 HNSW 向量索引（防全表扫描）

    enabled: bool = True
    host: str = "localhost"
    port: int = 5432
    db: str = "pipeline_rag_vector"
    user: str = "postgres"
    password: str = "5656"
    asyncpg_min_size: int = 2
    asyncpg_max_size: int = 10
    sqlalchemy_pool_size: int = 5
    sqlalchemy_max_overflow: int = 10

    @computed_field  # type: ignore[misc]
    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    @computed_field  # type: ignore[misc]
    @property
    def sync_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"
        )

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", env_file=_ENV_FILE, extra="ignore")
