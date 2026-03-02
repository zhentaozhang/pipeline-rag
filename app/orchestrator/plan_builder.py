"""
ExecutionPlan 构建工厂

所有方法收敛为接收 PrepareContext，消除 17 参数散列传递。
"""

from app.chat.schema import ExecutionPlan, SubQuestion
from app.common.enums import ChatQueryMode, ExecutionMode
from app.common.text_utils import safe_text
from app.config import get_settings
from app.orchestrator.context import PrepareContext
from app.orchestrator.fallback_router import FallbackRouter
from app.orchestrator.intent_detector import build_document_mode_no_evidence_reply


class PlanBuilder:
    @staticmethod
    def build_common_kwargs(ctx: PrepareContext) -> dict:
        """从 PrepareContext 构建 ExecutionPlan 公共字段"""
        question = ctx.rewritten_question or ctx.question
        sub_qs = ctx.rewrite_sub_questions or [question]
        ret_q = ctx.retrieval_question or question
        ret_sub_qs = ctx.retrieval_sub_questions or sub_qs

        return dict(
            original_question=ctx.question,
            agent_question=ctx.question,
            rewritten_question=question,
            rewrite_sub_questions=sub_qs,
            retrieval_question=ret_q,
            retrieval_sub_questions=ret_sub_qs,
            context_summary=ctx.history_summary,
            history_summary=ctx.history_summary,
            long_term_summary=safe_text(getattr(ctx.memory_ctx, "long_term_summary", "")),
            history_planning_context=ctx.history_planning_ctx,
            recent_history_transcript=safe_text(getattr(ctx.memory_ctx, "recent_transcript", "")),
            answer_recent_transcript=safe_text(
                getattr(ctx.memory_ctx, "answer_recent_transcript", "")
            ),
            answer_history_context=ctx.answer_history_ctx,
            current_date=str(ctx.current_date),
            current_date_text=ctx.current_date_text,
            requires_current_date_anchoring=ctx.requires_current_date_anchoring,
            requires_fresh_search=ctx.requires_fresh_search,
            history_compression_applied=getattr(ctx.memory_ctx, "compression_applied", False),
            history_covered_exchange_id=getattr(ctx.memory_ctx, "covered_exchange_id", None),
            history_covered_exchange_count=getattr(ctx.memory_ctx, "covered_exchange_count", None),
            history_compression_count=getattr(ctx.memory_ctx, "compression_count", None),
        )

    @staticmethod
    def build_refusal_plan(ctx: PrepareContext, block_reason: str) -> ExecutionPlan:
        settings = get_settings()
        return ExecutionPlan(
            mode=ExecutionMode.REFUSAL,
            chat_mode=ctx.chat_mode,
            refusal_reply=f"根据企业安全规范，该请求已被拦截：{block_reason}",
            no_evidence_reply=settings.rag.no_evidence_reply,
            **PlanBuilder.build_common_kwargs(ctx),
        )

    @staticmethod
    def build_open_chat_plan(ctx: PrepareContext) -> ExecutionPlan:
        settings = get_settings()
        return ExecutionPlan(
            mode=ExecutionMode.REACT_AGENT,
            chat_mode=ChatQueryMode.OPEN_CHAT,
            no_evidence_reply=settings.rag.no_evidence_reply,
            **PlanBuilder.build_common_kwargs(ctx),
        )

    @staticmethod
    def build_final_plan(ctx: PrepareContext) -> ExecutionPlan:
        routed_document_id = ctx.routed_document_id or (
            ctx.original_doc_ids[0] if ctx.original_doc_ids else ctx.original_selected_document_id
        )
        routed_document_name = ctx.routed_document_name or ctx.original_selected_document_name or ""
        routed_task_id = ctx.routed_task_id or ctx.original_selected_task_id
        routed_document_ids = ctx.top_doc_ids or (
            [routed_document_id] if routed_document_id else []
        )
        routed_task_ids = ctx.top_task_ids or ([routed_task_id] if routed_task_id else [])

        sub_questions = [
            SubQuestion(
                index=i,
                text=sq,
                original=ctx.question,
                tenant_id=ctx.tenant_id,
                scope_code=None,
                doc_ids=routed_document_ids,
            )
            for i, sq in enumerate(ctx.retrieval_sub_questions)
        ]

        chat_mode_out = (
            ChatQueryMode.AUTO_DOCUMENT
            if ctx.chat_mode == ChatQueryMode.AUTO_DOCUMENT
            else (ChatQueryMode.DOCUMENT if ctx.chat_mode == ChatQueryMode.DOCUMENT else None)
        )

        return ExecutionPlan(
            mode=ctx.execution_mode,
            tenant_id=ctx.tenant_id,
            sub_questions=sub_questions,
            is_time_sensitive=ctx.is_time_sensitive,
            selected_document_id=routed_document_id,
            selected_document_name=routed_document_name,
            selected_task_id=routed_task_id,
            retrieval_document_ids=routed_document_ids,
            retrieval_task_ids=routed_task_ids,
            navigation_decision=ctx.navigation_decision,
            chat_mode=chat_mode_out,
            no_evidence_reply=build_document_mode_no_evidence_reply(
                ctx.question, ctx.requires_fresh_search
            ),
            **PlanBuilder.build_common_kwargs(ctx),
        )

    # ── 澄清相关方法（不需要 PrepareContext，保持原样）───────────

    @staticmethod
    def build_clarification_reply(
        original_question: str,
        route_decision,
        candidate_documents: list,
    ) -> str:
        top_candidates = candidate_documents[:3] if candidate_documents else []
        if not top_candidates:
            return "当前我还不能稳定判断你想问哪份知识文档。请补充更具体的文档名、主题词，或者直接切换到\u201c当前文档问答\u201d后指定文档。"
        builder = ["这个问题目前存在文档范围歧义，我先确认你想问哪一份："]
        for idx, item in enumerate(top_candidates):
            name = item.document_name or item.document_id
            builder.append(f"{idx + 1}. 《{name}》")
            if item.scope_name or item.scope_code:
                scope = item.scope_name or item.scope_code
                builder[-1] += f"（{scope}）"
        builder.append("你可以直接回复文档名，或者改用\u201c当前文档问答\u201d模式明确指定文档。")
        return "\n".join(builder)

    @staticmethod
    def build_clarification_options(candidate_documents: list) -> list[str]:
        if not candidate_documents:
            return []
        return [f"我想问《{c.document_name or c.document_id}》" for c in candidate_documents[:3]]

    @staticmethod
    def build_clarification_reason(route_decision, candidate_documents: list) -> str:
        if not route_decision or not route_decision.documents:
            return "当前自动知识路由没有形成稳定候选，已改为先向用户确认文档范围。"
        confidence_text = (
            route_decision.confidence.to_plain_string()
            if hasattr(route_decision.confidence, "to_plain_string")
            else str(route_decision.confidence)
            if route_decision.confidence
            else "-"
        )
        candidate_count = len(candidate_documents) if candidate_documents else 0
        return f"当前自动知识路由置信度为 {confidence_text}，候选文档数为 {candidate_count}，为避免误选文档，先返回澄清问题。\n"

    @staticmethod
    def should_ask_clarification(
        route_decision,
        candidate_documents: list,
        threshold: float = 0.40,
        question: str = "",
    ) -> bool:
        if not candidate_documents:
            return True
        if not route_decision or not route_decision.documents:
            return True
        confidence_val = float(route_decision.confidence) if route_decision.confidence else 0.0
        if confidence_val < threshold:
            if question and confidence_val >= 0.25:
                doc_keywords = FallbackRouter.extract_keywords_from_doc_name(
                    candidate_documents[0].document_name
                )
                if doc_keywords and any(kw in question.lower() for kw in doc_keywords):
                    return False
            return True
        if len(candidate_documents) < 2:
            return False
        top_score = candidate_documents[0].score
        second_score = candidate_documents[1].score
        if top_score is None or second_score is None:
            return False
        score_diff = float(top_score) - float(second_score)
        return (
            score_diff <= 3.0
            and candidate_documents[0].scope_code != candidate_documents[1].scope_code
        )
