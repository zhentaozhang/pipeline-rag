"""add_observability_v2_tables

Create trace_observability, trace_observability_span, trace_observability_score
as the new unified observability + evaluation storage.

Revision ID: 0a72004072e8
Revises: 052a337bd8b2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0a72004072e8"
down_revision: str | None = "052a337bd8b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trace_observability",
        sa.Column("trace_id", sa.String(64), primary_key=True),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("exchange_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("root_span_id", sa.String(64), nullable=True),
        sa.Column("input", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(3), nullable=False),
        sa.Column("flushed_at", sa.DateTime(3), nullable=True),
    )
    op.create_index("idx_obs_conv_exch", "trace_observability", ["conversation_id", "exchange_id"])
    op.create_index("idx_obs_created", "trace_observability", ["created_at"])

    op.create_table(
        "trace_observability_span",
        sa.Column("span_id", sa.String(64), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("parent_span_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("started_at", sa.DateTime(3), nullable=False),
        sa.Column("ended_at", sa.DateTime(3), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["trace_id"], ["trace_observability.trace_id"]),
    )
    op.create_index("idx_span_trace", "trace_observability_span", ["trace_id"])
    op.create_index("idx_span_parent", "trace_observability_span", ["parent_span_id"])

    op.create_table(
        "trace_observability_score",
        sa.Column("score_id", sa.String(64), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("span_id", sa.String(64), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=False),
        sa.Column("value", sa.DECIMAL(5, 4), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(3), nullable=False),
        sa.ForeignKeyConstraint(["trace_id"], ["trace_observability.trace_id"]),
        sa.ForeignKeyConstraint(["span_id"], ["trace_observability_span.span_id"]),
    )
    op.create_index("idx_score_trace", "trace_observability_score", ["trace_id"])
    op.create_index("idx_score_metric", "trace_observability_score", ["metric_name"])


def downgrade() -> None:
    op.drop_table("trace_observability_score")
    op.drop_table("trace_observability_span")
    op.drop_table("trace_observability")
