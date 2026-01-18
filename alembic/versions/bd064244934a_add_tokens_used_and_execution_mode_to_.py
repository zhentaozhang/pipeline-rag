"""add_tokens_used_and_execution_mode_to_exchange

Revision ID: bd064244934a
Revises: 041e6530056f
Create Date: 2026-05-31 15:56:01.705448

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bd064244934a"
down_revision: str | None = "041e6530056f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipeline_rag_chat_exchange",
        sa.Column("tokens_used", sa.BigInteger(), nullable=True, comment="消耗 token 数"),
    )
    op.add_column(
        "pipeline_rag_chat_exchange",
        sa.Column("execution_mode", sa.String(length=32), nullable=True, comment="执行模式"),
    )


def downgrade() -> None:
    op.drop_column("pipeline_rag_chat_exchange", "execution_mode")
    op.drop_column("pipeline_rag_chat_exchange", "tokens_used")
