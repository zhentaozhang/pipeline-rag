"""Alembic env.py — 动态读取数据库 URL + 自动发现所有 ORM 模型"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# ── 加载配置 ───────────────────────────────────────────────────────────────
config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# ── 导入所有模型（Alembic 才能感知表结构变化）────────────────────────────────
from app.db.models import models  # noqa: F401 — 触发模型注册
from app.db.session import Base

target_metadata = Base.metadata

# 非 ORM 管理表：app 用原生 SQL 读写（app/observability/storage.py），由 baseline 显式创建。
# autogenerate 忽略它们，避免被误判为“多余表”而生成 drop_table。
_EXTERNAL_TABLES = {
    "trace_observability",
    "trace_observability_span",
    "trace_observability_score",
}


def _include_object(obj, name, type_, reflected, compare_to):
    is_external_table = type_ == "table" and name in _EXTERNAL_TABLES
    is_external_index = (
        type_ == "index"
        and getattr(obj, "table", None) is not None
        and obj.table.name in _EXTERNAL_TABLES
    )
    return not (is_external_table or is_external_index)


# ── 从 Pydantic Settings 动态读取 DSN（不依赖 alembic.ini 硬编码）────────────
def get_url() -> str:
    from app.config import get_settings

    return get_settings().mysql.sync_url


def run_migrations_offline() -> None:
    """离线模式（只生成 SQL 脚本，不连接数据库）"""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式（直接连接数据库执行迁移）"""
    connectable = engine_from_config(
        {"sqlalchemy.url": get_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
