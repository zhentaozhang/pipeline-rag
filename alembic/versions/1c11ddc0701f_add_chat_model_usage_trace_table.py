"""add_chat_model_usage_trace_table

Revision ID: 1c11ddc0701f
Revises: 690151807873
Create Date: 2026-05-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c11ddc0701f"
down_revision: str | None = "690151807873"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_model_usage_trace",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("exchange_id", sa.String(length=64), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("stage_code", sa.String(length=64), nullable=True),
        sa.Column("usage_type", sa.String(length=32), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_model_usage_trace_trace_id"),
        "chat_model_usage_trace",
        ["trace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_model_usage_trace_exchange_id"),
        "chat_model_usage_trace",
        ["exchange_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_model_usage_trace_session_id"),
        "chat_model_usage_trace",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_model_usage_trace_session_id"), table_name="chat_model_usage_trace")
    op.drop_index(
        op.f("ix_chat_model_usage_trace_exchange_id"), table_name="chat_model_usage_trace"
    )
    op.drop_index(op.f("ix_chat_model_usage_trace_trace_id"), table_name="chat_model_usage_trace")
    op.drop_table("chat_model_usage_trace")
