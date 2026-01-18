"""recreate_missing_tables_and_fix_columns

Revision ID: 690151807873
Revises: c38283c3e66b
Create Date: 2026-05-25 03:24:53.239907

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "690151807873"
down_revision: str | None = "c38283c3e66b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. CREATE missing tables (11 tables) ──────────────────────────────────

    op.create_table(
        "graph_checkpoint",
        sa.Column("checkpoint_id", sa.String(128), nullable=False),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("node_id", sa.String(128), nullable=True),
        sa.Column("next_node_id", sa.String(128), nullable=True),
        sa.Column("state_data", sa.Text(), nullable=True),
        sa.Column("saved_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("checkpoint_id"),
    )
    op.create_index(
        op.f("ix_graph_checkpoint_thread_id"), "graph_checkpoint", ["thread_id"], unique=False
    )

    op.create_table(
        "graph_thread",
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("thread_name", sa.String(255), nullable=False),
        sa.Column("is_released", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("thread_id"),
    )

    op.create_table(
        "pipeline_rag_document_task_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(128), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_type", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Integer(), nullable=False),
        sa.Column("log_level", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("operator_type", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "operator_id", sa.String(128), nullable=False, server_default=sa.text("'system'")
        ),
        sa.Column("content", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pipeline_rag_document_task_log_task_id"),
        "pipeline_rag_document_task_log",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pipeline_rag_document_task_log_document_id"),
        "pipeline_rag_document_task_log",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "document_profile",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "document_id", sa.BigInteger(), sa.ForeignKey("pipeline_rag_document.id"), nullable=False
        ),
        sa.Column("profile_status", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("document_summary", sa.Text(), nullable=True),
        sa.Column("core_topics", sa.Text(), nullable=True),
        sa.Column("example_questions", sa.Text(), nullable=True),
        sa.Column("document_type", sa.String(64), nullable=True),
        sa.Column("knowledge_domain", sa.String(128), nullable=True),
        sa.Column("business_category", sa.String(128), nullable=True),
        sa.Column("graph_friendly", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )

    op.create_table(
        "topic_document_relation",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("topic_id", sa.BigInteger(), sa.ForeignKey("knowledge_topic.id"), nullable=False),
        sa.Column("topic_code", sa.String(64), nullable=False),
        sa.Column(
            "document_id", sa.BigInteger(), sa.ForeignKey("pipeline_rag_document.id"), nullable=False
        ),
        sa.Column("relation_score", sa.Float(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pipeline_rag_document_strategy_plan",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=True),
        sa.Column("plan_source", sa.Integer(), nullable=True),
        sa.Column("plan_status", sa.Integer(), nullable=True),
        sa.Column("strategy_count", sa.Integer(), nullable=True),
        sa.Column("strategy_snapshot", sa.Text(), nullable=True),
        sa.Column("recommend_reason", sa.Text(), nullable=True),
        sa.Column("adjust_note", sa.Text(), nullable=True),
        sa.Column("confirm_user_id", sa.BigInteger(), nullable=True),
        sa.Column("confirm_time", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pipeline_rag_document_strategy_step",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=True),
        sa.Column("pipeline_type", sa.String(64), nullable=True),
        sa.Column("strategy_type", sa.Integer(), nullable=True),
        sa.Column("strategy_role", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.Integer(), nullable=True),
        sa.Column("execute_status", sa.Integer(), nullable=True),
        sa.Column("recommend_reason", sa.Text(), nullable=True),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pipeline_rag_document_parent_block",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("plan_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_no", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.Integer(), nullable=True),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("structure_node_id", sa.BigInteger(), nullable=True),
        sa.Column("structure_node_type", sa.Integer(), nullable=True),
        sa.Column("canonical_path", sa.Text(), nullable=True),
        sa.Column("item_index", sa.Integer(), nullable=True),
        sa.Column("parent_text", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("child_count", sa.Integer(), nullable=True),
        sa.Column("start_chunk_no", sa.Integer(), nullable=True),
        sa.Column("end_chunk_no", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pipeline_rag_document_structure_node",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=True),
        sa.Column("parse_task_id", sa.String(64), nullable=True),
        sa.Column("node_no", sa.Integer(), nullable=True),
        sa.Column("node_type", sa.Integer(), nullable=True),
        sa.Column("parent_node_id", sa.BigInteger(), nullable=True),
        sa.Column("prev_sibling_node_id", sa.BigInteger(), nullable=True),
        sa.Column("next_sibling_node_id", sa.BigInteger(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("node_code", sa.String(128), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("anchor_text", sa.Text(), nullable=True),
        sa.Column("canonical_path", sa.Text(), nullable=True),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("item_index", sa.Integer(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "knowledge_route_trace",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("exchange_id", sa.BigInteger(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("rewrite_question", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(32), nullable=True),
        sa.Column("top_scopes_json", sa.Text(), nullable=True),
        sa.Column("top_topics_json", sa.Text(), nullable=True),
        sa.Column("top_documents_json", sa.Text(), nullable=True),
        sa.Column("selected_document_id", sa.BigInteger(), nullable=True),
        sa.Column("hit_selected_document", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("route_status", sa.Integer(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_route_trace_conversation_id"),
        "knowledge_route_trace",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_route_trace_exchange_id"),
        "knowledge_route_trace",
        ["exchange_id"],
        unique=False,
    )

    op.create_table(
        "pipeline_rag_chat_stage_benchmark",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("exchange_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_code", sa.String(64), nullable=False),
        sa.Column("execution_mode", sa.String(32), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pipeline_rag_chat_stage_benchmark_conversation_id"),
        "pipeline_rag_chat_stage_benchmark",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pipeline_rag_chat_stage_benchmark_exchange_id"),
        "pipeline_rag_chat_stage_benchmark",
        ["exchange_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pipeline_rag_chat_stage_benchmark_stage_code"),
        "pipeline_rag_chat_stage_benchmark",
        ["stage_code"],
        unique=False,
    )

    # ── 2. ADD missing columns to conversation_exchange ───────────────────────
    op.add_column("conversation_exchange", sa.Column("thinking_steps", sa.Text(), nullable=True))
    op.add_column("conversation_exchange", sa.Column("references", sa.Text(), nullable=True))
    op.add_column("conversation_exchange", sa.Column("recommendations", sa.Text(), nullable=True))
    op.add_column("conversation_exchange", sa.Column("used_tools", sa.Text(), nullable=True))
    op.add_column("conversation_exchange", sa.Column("debug_trace_json", sa.Text(), nullable=True))
    op.add_column("conversation_exchange", sa.Column("turn_status", sa.Integer(), nullable=True))
    op.add_column(
        "conversation_exchange", sa.Column("first_response_time_ms", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "conversation_exchange", sa.Column("total_response_time_ms", sa.BigInteger(), nullable=True)
    )

    # ── 3. ADD missing columns to conversation_channel_execution ──────────────
    op.add_column(
        "conversation_channel_execution", sa.Column("trace_id", sa.String(64), nullable=True)
    )
    op.add_column(
        "conversation_channel_execution",
        sa.Column("sub_question_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "conversation_channel_execution",
        sa.Column(
            "execution_state", sa.String(32), nullable=False, server_default=sa.text("'SUCCESS'")
        ),
    )
    op.add_column(
        "conversation_channel_execution", sa.Column("start_time", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "conversation_channel_execution", sa.Column("end_time", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "conversation_channel_execution",
        sa.Column("duration_ms", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "conversation_channel_execution",
        sa.Column(
            "final_selected_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "conversation_channel_execution",
        sa.Column("avg_score", sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "conversation_channel_execution",
        sa.Column("max_score", sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "conversation_channel_execution",
        sa.Column("min_score", sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "conversation_channel_execution", sa.Column("config_snapshot", sa.Text(), nullable=True)
    )
    op.add_column(
        "conversation_channel_execution", sa.Column("error_message", sa.Text(), nullable=True)
    )

    # ── 4. ADD missing columns to conversation_retrieval_result ───────────────
    op.add_column(
        "conversation_retrieval_result", sa.Column("channel_type", sa.String(32), nullable=True)
    )
    op.add_column(
        "conversation_retrieval_result", sa.Column("original_score", sa.Float(), nullable=True)
    )
    op.add_column(
        "conversation_retrieval_result", sa.Column("rrf_score", sa.Float(), nullable=True)
    )
    op.add_column(
        "conversation_retrieval_result", sa.Column("rerank_score", sa.Float(), nullable=True)
    )
    op.add_column(
        "conversation_retrieval_result", sa.Column("document_id", sa.String(64), nullable=True)
    )
    op.add_column(
        "conversation_retrieval_result", sa.Column("document_name", sa.String(256), nullable=True)
    )
    op.add_column(
        "conversation_retrieval_result", sa.Column("chunk_no", sa.Integer(), nullable=True)
    )
    op.add_column(
        "conversation_retrieval_result",
        sa.Column("gate_passed", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column(
        "conversation_retrieval_result",
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "conversation_retrieval_result", sa.Column("selection_reason", sa.Text(), nullable=True)
    )

    # ── 5. ALTER column types: document.parse_status, document.index_status ──
    op.alter_column(
        "pipeline_rag_document",
        "parse_status",
        existing_type=sa.String(32),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.alter_column(
        "pipeline_rag_document",
        "index_status",
        existing_type=sa.String(32),
        type_=sa.Integer(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # ── Revert column type changes ────────────────────────────────────────────
    op.alter_column(
        "pipeline_rag_document",
        "index_status",
        existing_type=sa.Integer(),
        type_=sa.String(32),
        existing_nullable=False,
    )
    op.alter_column(
        "pipeline_rag_document",
        "parse_status",
        existing_type=sa.Integer(),
        type_=sa.String(32),
        existing_nullable=False,
    )

    # ── Drop added columns from conversation_retrieval_result ─────────────────
    op.drop_column("conversation_retrieval_result", "selection_reason")
    op.drop_column("conversation_retrieval_result", "is_selected")
    op.drop_column("conversation_retrieval_result", "gate_passed")
    op.drop_column("conversation_retrieval_result", "chunk_no")
    op.drop_column("conversation_retrieval_result", "document_name")
    op.drop_column("conversation_retrieval_result", "document_id")
    op.drop_column("conversation_retrieval_result", "rerank_score")
    op.drop_column("conversation_retrieval_result", "rrf_score")
    op.drop_column("conversation_retrieval_result", "original_score")
    op.drop_column("conversation_retrieval_result", "channel_type")

    # ── Drop added columns from conversation_channel_execution ────────────────
    op.drop_column("conversation_channel_execution", "error_message")
    op.drop_column("conversation_channel_execution", "config_snapshot")
    op.drop_column("conversation_channel_execution", "min_score")
    op.drop_column("conversation_channel_execution", "max_score")
    op.drop_column("conversation_channel_execution", "avg_score")
    op.drop_column("conversation_channel_execution", "final_selected_count")
    op.drop_column("conversation_channel_execution", "duration_ms")
    op.drop_column("conversation_channel_execution", "end_time")
    op.drop_column("conversation_channel_execution", "start_time")
    op.drop_column("conversation_channel_execution", "execution_state")
    op.drop_column("conversation_channel_execution", "sub_question_index")
    op.drop_column("conversation_channel_execution", "trace_id")

    # ── Drop added columns from conversation_exchange ─────────────────────────
    op.drop_column("conversation_exchange", "total_response_time_ms")
    op.drop_column("conversation_exchange", "first_response_time_ms")
    op.drop_column("conversation_exchange", "turn_status")
    op.drop_column("conversation_exchange", "debug_trace_json")
    op.drop_column("conversation_exchange", "used_tools")
    op.drop_column("conversation_exchange", "recommendations")
    op.drop_column("conversation_exchange", "references")
    op.drop_column("conversation_exchange", "thinking_steps")

    # ── Drop created tables (reverse order) ───────────────────────────────────
    op.drop_index(
        op.f("ix_pipeline_rag_chat_stage_benchmark_stage_code"),
        table_name="pipeline_rag_chat_stage_benchmark",
    )
    op.drop_index(
        op.f("ix_pipeline_rag_chat_stage_benchmark_exchange_id"),
        table_name="pipeline_rag_chat_stage_benchmark",
    )
    op.drop_index(
        op.f("ix_pipeline_rag_chat_stage_benchmark_conversation_id"),
        table_name="pipeline_rag_chat_stage_benchmark",
    )
    op.drop_table("pipeline_rag_chat_stage_benchmark")

    op.drop_index(op.f("ix_knowledge_route_trace_exchange_id"), table_name="knowledge_route_trace")
    op.drop_index(
        op.f("ix_knowledge_route_trace_conversation_id"), table_name="knowledge_route_trace"
    )
    op.drop_table("knowledge_route_trace")

    op.drop_table("pipeline_rag_document_structure_node")
    op.drop_table("pipeline_rag_document_parent_block")
    op.drop_table("pipeline_rag_document_strategy_step")
    op.drop_table("pipeline_rag_document_strategy_plan")
    op.drop_table("topic_document_relation")
    op.drop_table("document_profile")

    op.drop_index(
        op.f("ix_pipeline_rag_document_task_log_document_id"),
        table_name="pipeline_rag_document_task_log",
    )
    op.drop_index(
        op.f("ix_pipeline_rag_document_task_log_task_id"), table_name="pipeline_rag_document_task_log"
    )
    op.drop_table("pipeline_rag_document_task_log")

    op.drop_table("graph_thread")
    op.drop_index(op.f("ix_graph_checkpoint_thread_id"), table_name="graph_checkpoint")
    op.drop_table("graph_checkpoint")
