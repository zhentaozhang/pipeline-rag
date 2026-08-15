"""add_feishu_binding

P3-4：飞书 IM 会话 ↔ 平台会话映射表（(chat_id, open_id) 维度独立上下文）。

Revision ID: d7a1f2c3b4e5
Revises: 9c2e5f71a0b4
Create Date: 2026-08-15 21:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7a1f2c3b4e5"
down_revision: str | None = "9c2e5f71a0b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feishu_binding",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("open_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_feishu_binding_chat_id", "feishu_binding", ["chat_id"])
    op.create_index("ix_feishu_binding_conversation_id", "feishu_binding", ["conversation_id"])
    op.create_unique_constraint("uk_feishu_binding_chat_open", "feishu_binding", ["chat_id", "open_id"])


def downgrade() -> None:
    op.drop_table("feishu_binding")
