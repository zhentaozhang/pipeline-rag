"""drop_langgraph_checkpoint_tables

P2-1：彻底移除 LangGraph checkpoint 持久化体系。
删除 5 张表：LangGraph 原生 checkpoint / checkpoint_blobs / checkpoint_writes
（AIOMySQLSaver 已从 Agent 执行器移除），以及从未有写入方的自定义
graph_checkpoint / graph_thread。

Revision ID: 9c2e5f71a0b4
Revises: 4a5b4bbdfcaf
Create Date: 2026-08-15 20:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "9c2e5f71a0b4"
down_revision: str | None = "0a72004072e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROPPED_TABLES = [
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoint",
    "graph_thread",
    "graph_checkpoint",
]


def upgrade() -> None:
    for table in _DROPPED_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")


def downgrade() -> None:
    # checkpoint 三表结构由 langgraph-checkpoint-mysql 库管理（AIOMySQLSaver.setup），
    # 此处不再重建；如需恢复可重新引入该依赖后执行 setup。
    pass
