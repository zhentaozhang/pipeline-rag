"""fix missing columns in knowledge_scope, knowledge_topic, document_profile, topic_document_relation

Revision ID: 608801d3f53a
Revises: 1c11ddc0701f
Create Date: 2026-05-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "608801d3f53a"
down_revision: str | None = "1c11ddc0701f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. knowledge_scope: add missing columns ────────────────────────────
    op.add_column("knowledge_scope", sa.Column("parent_scope_code", sa.String(64), nullable=True))
    op.add_column("knowledge_scope", sa.Column("aliases", sa.Text(), nullable=True))
    op.add_column("knowledge_scope", sa.Column("examples", sa.Text(), nullable=True))
    op.add_column("knowledge_scope", sa.Column("sort_order", sa.Integer(), nullable=True))

    # ── 2. knowledge_topic: add missing columns ────────────────────────────
    op.add_column("knowledge_topic", sa.Column("scope_code", sa.String(64), nullable=True))
    op.add_column("knowledge_topic", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("aliases", sa.Text(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("examples", sa.Text(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("answer_shape", sa.Text(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("execution_preference", sa.Text(), nullable=True))
    op.add_column("knowledge_topic", sa.Column("sort_order", sa.Integer(), nullable=True))

    # ── 3. document_profile: add missing columns ───────────────────────────
    op.add_column(
        "document_profile",
        sa.Column("profile_version", sa.Integer(), server_default=sa.text("1"), nullable=True),
    )
    op.add_column(
        "document_profile", sa.Column("knowledge_scope_code", sa.String(64), nullable=True)
    )
    op.add_column(
        "document_profile", sa.Column("knowledge_scope_name", sa.String(128), nullable=True)
    )
    op.add_column("document_profile", sa.Column("document_tags", sa.String(256), nullable=True))
    op.add_column(
        "document_profile",
        sa.Column(
            "supports_graph_outline", sa.Boolean(), server_default=sa.text("0"), nullable=True
        ),
    )
    op.add_column(
        "document_profile",
        sa.Column("supports_item_lookup", sa.Boolean(), server_default=sa.text("0"), nullable=True),
    )
    op.add_column(
        "document_profile",
        sa.Column(
            "supports_graph_assist", sa.Boolean(), server_default=sa.text("1"), nullable=True
        ),
    )

    # ── 4. topic_document_relation: add missing columns ────────────────────
    op.add_column(
        "topic_document_relation", sa.Column("relation_source", sa.String(64), nullable=True)
    )
    op.add_column("topic_document_relation", sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    # ── Revert topic_document_relation columns ─────────────────────────────
    op.drop_column("topic_document_relation", "reason")
    op.drop_column("topic_document_relation", "relation_source")

    # ── Revert document_profile columns ────────────────────────────────────
    op.drop_column("document_profile", "supports_graph_assist")
    op.drop_column("document_profile", "supports_item_lookup")
    op.drop_column("document_profile", "supports_graph_outline")
    op.drop_column("document_profile", "document_tags")
    op.drop_column("document_profile", "knowledge_scope_name")
    op.drop_column("document_profile", "knowledge_scope_code")
    op.drop_column("document_profile", "profile_version")

    # ── Revert knowledge_topic columns ─────────────────────────────────────
    op.drop_column("knowledge_topic", "sort_order")
    op.drop_column("knowledge_topic", "execution_preference")
    op.drop_column("knowledge_topic", "answer_shape")
    op.drop_column("knowledge_topic", "examples")
    op.drop_column("knowledge_topic", "aliases")
    op.drop_column("knowledge_topic", "description")
    op.drop_column("knowledge_topic", "scope_code")

    # ── Revert knowledge_scope columns ─────────────────────────────────────
    op.drop_column("knowledge_scope", "sort_order")
    op.drop_column("knowledge_scope", "examples")
    op.drop_column("knowledge_scope", "aliases")
    op.drop_column("knowledge_scope", "parent_scope_code")
