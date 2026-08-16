"""fix_trace_exchange_id_bigint

P2-2 遗留真 bug：trace_observability.exchange_id 为 INT，存不下 snowflake 大 ID
（208886...），真实请求的 trace flush 全部 DataError(1264) 失败——Trace UI 实际为空。
迁移：exchange_id INT → BIGINT。

Revision ID: e2f3a4b5c6d7
Revises: d7a1f2c3b4e5
Create Date: 2026-08-16 15:55:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d7a1f2c3b4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("trace_observability", "exchange_id", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("trace_observability", "exchange_id", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=False)
