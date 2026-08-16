"""
Prompt 组装 + PromptBudget 控制

包含：跨子问题引用去重、预算控制、文档/网页引用分离渲染、引用复用/省略标记、snippet 截断
"""

import structlog

from app.chat.schema import Evidence, ExecutionPlan, PromptAssemblyResult, SubQuestionEvidence
from app.common.jinja import jinja_env
from app.config import get_settings
from app.observability.metrics import CONTEXT_TRUNCATION_TOTAL, CONTEXT_WINDOW_UTILIZATION

logger = structlog.get_logger(__name__)
settings = get_settings()


# ── PromptBudget ───────────────────────────────────────────────────────────


class PromptBudget:
    def __init__(self, total_budget: int, per_sub_question_budget: int):
        self.total_budget = max(0, total_budget)
        self.per_sub_question_budget = max(0, per_sub_question_budget)
        self.remaining_total = self.total_budget
        self.remaining_sub_question = self.per_sub_question_budget
        self.rendered_reference_count = 0
        self.omitted_reference_count = 0
        self.rendered_reference_details: list[str] = []
        self.omitted_reference_details: list[str] = []

    def reset_sub_question_budget(self) -> None:
        self.remaining_sub_question = self.per_sub_question_budget

    def try_consume(self, size: int) -> bool:
        if self.total_budget <= 0 or self.per_sub_question_budget <= 0:
            return False
        if size > self.remaining_total or size > self.remaining_sub_question:
            return False
        self.remaining_total -= size
        self.remaining_sub_question -= size
        return True

    def mark_rendered(self, detail: str) -> None:
        self.rendered_reference_count += 1
        if detail:
            self.rendered_reference_details.append(detail)

    def mark_omitted(self, detail: str) -> None:
        self.omitted_reference_count += 1
        if detail:
            self.omitted_reference_details.append(detail)


class PromptAssemblyService:
    """
    Prompt 组装服务。
    """

    def __init__(self) -> None:
        self._jinja = jinja_env

    def assemble(
        self,
        plan: ExecutionPlan,
        sub_evidences: list[SubQuestionEvidence],
    ) -> PromptAssemblyResult:
        """完整组装：跨子问题引用去重 → system_prompt + user_prompt + budget 控制"""
        # ── Step 1: 跨子问题引用去重 + reference_id 映射 ──────────
        deduped, reference_map = self._dedup_evidences(sub_evidences)

        # ── Step 2: 预算控制 + Prompt 渲染 ────────────────────────
        budget = PromptBudget(
            max(0, settings.rag.prompt_budget_total),
            max(0, settings.rag.prompt_budget_per_subquestion),
        )
        rendered_reference_keys: set[str] = set()

        system_prompt = self._build_system_prompt(plan)
        user_prompt = self._build_user_prompt(plan, deduped, budget, rendered_reference_keys)

        # ── Step 3: Context Window 预检 ────────────────────────────
        raw_total = len(system_prompt) + len(user_prompt)
        estimated_tokens = self._estimate_tokens(raw_total)
        context_limit = settings.llm.context_window_limit
        actual_limit = int(context_limit * (1.0 - settings.rag.context_window_safety_margin))
        utilization = estimated_tokens / context_limit if context_limit > 0 else 0.0
        CONTEXT_WINDOW_UTILIZATION.set(utilization)

        truncation_count = 0
        while estimated_tokens > actual_limit and budget.total_budget > 500:
            truncation_count += 1
            old_total = budget.total_budget
            budget.total_budget = max(500, int(budget.total_budget * 0.7))
            reduction = old_total - budget.total_budget
            CONTEXT_TRUNCATION_TOTAL.labels(reason="exceeds_context_window").inc()
            logger.warning(
                "context window truncation",
                estimated_tokens=estimated_tokens,
                context_limit=context_limit,
                actual_limit=actual_limit,
                budget_reduction=reduction,
                new_budget=budget.total_budget,
            )
            user_prompt = self._build_user_prompt(plan, deduped, budget, rendered_reference_keys)
            raw_total = len(system_prompt) + len(user_prompt)
            estimated_tokens = self._estimate_tokens(raw_total)
            utilization = estimated_tokens / context_limit if context_limit > 0 else 0.0
            CONTEXT_WINDOW_UTILIZATION.set(utilization)

        if truncation_count > 0:
            logger.info(
                "context window re-balance completed",
                truncation_rounds=truncation_count,
                final_utilization=f"{utilization:.1%}",
                rendered_refs=budget.rendered_reference_count,
                omitted_refs=budget.omitted_reference_count,
            )

        return PromptAssemblyResult(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            total_budget=budget.total_budget,
            per_sub_question_budget=budget.per_sub_question_budget,
            rendered_reference_count=budget.rendered_reference_count,
            omitted_reference_count=budget.omitted_reference_count,
            rendered_reference_details=list(budget.rendered_reference_details),
            omitted_reference_details=list(budget.omitted_reference_details),
        )

    @staticmethod
    def _dedup_evidences(
        sub_evidences: list[SubQuestionEvidence],
    ) -> tuple[list[SubQuestionEvidence], dict[str, int]]:
        """跨子问题引用去重 + reference_id 映射。"""
        reference_map: dict[str, int] = {}
        rendered_reference_keys: set[str] = set()
        result: list[SubQuestionEvidence] = []

        for sub_ev in sub_evidences:
            allocated_evidences: list[Evidence] = []

            for ev in sub_ev.evidences:
                if ev.chunk_id in rendered_reference_keys:
                    ev = ev.model_copy()
                    if ev.reference_id is not None:
                        reference_map[ev.chunk_id] = ev.reference_id
                        ev.content = f"请参考引用 [{ev.reference_id}]"
                    else:
                        ev.content = "（内容同上条引用）"
                    allocated_evidences.append(ev)
                    continue

                ev = ev.model_copy()
                if ev.reference_id is not None:
                    reference_map[ev.chunk_id] = ev.reference_id
                rendered_reference_keys.add(ev.chunk_id)
                allocated_evidences.append(ev)

            result.append(
                SubQuestionEvidence(
                    sub_question=sub_ev.sub_question,
                    evidences=allocated_evidences,
                    channel_trace=sub_ev.channel_trace,
                )
            )

        logger.info(
            "evidence_deduped",
            references=len(reference_map),
            sub_questions=len(result),
        )
        return result, reference_map

    def _build_system_prompt(self, plan) -> str:
        base = (
            settings.rag.answer_system_prompt.strip()
            if settings.rag.answer_system_prompt and settings.rag.answer_system_prompt.strip()
            else (
                "你是 Pipeline RAG 的企业知识问答助手。\n"
                "你必须严格基于给定证据回答，不要编造证据中没有出现的事实。\n"
                '如果提供了"对话承接上下文"，它只用于理解当前问题中的指代关系，不能替代证据材料，也不能作为事实来源。\n'
                "如果证据不足以支持明确结论，请直接说明资料不足。\n"
                "引用纪律：仅在证据直接支持某论断时，才在该句末尾标注对应引用编号；\n"
                "若某论断没有任何证据支持（包括证据只提及相似主题但未直接说明），不得标注引用，\n"
                "并明确说明'手册/资料中未提及该内容'。\n"
                "如果问题被拆成多个子问题，请按编号逐一回答。\n"
                "如果引用了证据，请在对应句子末尾标注 [1][2] 这样的引用编号。"
            )
        )
        # D 项：回答长度上限约束（RAG_ANSWER_MAX_CHARS>0 时注入）
        if (getattr(settings.rag, "answer_max_chars", 0) or 0) > 0:
            base += (
                f"\n回答长度约束：本次回答请简明扼要，总字数控制在 "
                f"{settings.rag.answer_max_chars} 字以内，直接给出结论与关键要点，不要展开背景。"
            )
        # P3 用户事实记忆（Mem0 式）：注入已记忆的用户事实/偏好（个性化，不编造）
        user_memory = getattr(plan, "user_memory_context", None) or []
        if user_memory:
            facts_block = "\n".join(f"- {f}" for f in user_memory)
            base += (
                "\n\n已知的用户长期信息（来自跨轮记忆）：\n"
                f"{facts_block}\n"
                "回答时可结合这些信息提供个性化服务，但不得编造记忆之外的用户信息。"
            )
        return base

    def _build_user_prompt(
        self,
        plan: ExecutionPlan,
        sub_evidences: list[SubQuestionEvidence],
        budget: PromptBudget,
        rendered_keys: set[str],
    ) -> str:
        """构建 user prompt（渲染 rag_answer.j2 模板）。"""
        template = self._jinja.get_template("rag_answer.j2")

        # Build evidence blocks with budget control
        evidence_blocks = self._build_evidence_blocks(sub_evidences, rendered_keys, budget)

        # Build sub-questions section
        has_sub_questions = len(plan.sub_questions) > 1 or len(plan.retrieval_sub_questions) > 1
        sub_questions_text = ""
        if has_sub_questions:
            sq_list = plan.retrieval_sub_questions or [sq.text for sq in plan.sub_questions]
            sub_questions_text = "\n".join(f"{i + 1}. {sq}" for i, sq in enumerate(sq_list))

        # Build history context
        has_history = (
            plan.answer_history_context and not plan.answer_history_context.is_empty
            if hasattr(plan.answer_history_context, "is_empty")
            else bool(getattr(plan, "answer_recent_transcript", "") or "")
        )
        history_context = ""
        if plan.answer_history_context:
            history_context = getattr(plan.answer_history_context, "rendered_text", "") or getattr(
                plan, "answer_recent_transcript", ""
            )

        retrieval_question = plan.retrieval_question or ""
        has_retrieval = bool(
            retrieval_question.strip() and retrieval_question != plan.original_question
        )

        return template.render(
            original_question=plan.original_question or plan.retrieval_question or "",
            has_retrieval_question=has_retrieval,
            retrieval_question=retrieval_question,
            has_history_context=has_history,
            history_context=history_context,
            has_sub_questions=has_sub_questions,
            sub_questions=sub_questions_text,
            current_date=plan.current_date_text or "",
            evidence_blocks=evidence_blocks,
        )

    def _build_evidence_blocks(
        self,
        sub_evidences: list[SubQuestionEvidence],
        rendered_keys: set[str],
        budget: PromptBudget,
    ) -> str:
        blocks = []
        for i, se in enumerate(sub_evidences):
            budget.reset_sub_question_budget()
            ref_text = self._append_references(se.evidences, rendered_keys, budget)
            idx = i + 1
            blocks.append(f"## 子问题{idx}：{se.sub_question.text}\n{ref_text}")
        return "\n\n".join(blocks)

    def _append_references(
        self,
        evidences: list[Evidence],
        rendered_keys: set[str],
        budget: PromptBudget,
    ) -> str:
        if not evidences:
            return "- 当前子问题没有检索到证据"

        builder = []
        omitted = False

        for ev in evidences:
            unique_key = self._unique_key(ev)
            if unique_key in rendered_keys:
                reuse_line = f"- 复用证据 [{ev.reference_id or ''}]"
                if budget.try_consume(len(reuse_line)):
                    builder.append(reuse_line)
                continue

            block = self._render_reference_block(ev)
            if budget.try_consume(len(block)):
                builder.append(block)
                rendered_keys.add(unique_key)
                budget.mark_rendered(self._reference_summary(ev, "已纳入 Prompt"))
            else:
                omitted = True
                budget.mark_omitted(self._reference_summary(ev, "超出上下文预算，已省略"))
                break

        if omitted:
            builder.append("- 其余证据因上下文预算限制已省略")

        return "\n".join(builder)

    def _render_reference_block(self, ev: Evidence) -> str:
        """渲染单个引用块（区分网页和文档）。"""
        if ev.source_type == "web":
            return self._render_web_reference(ev)
        return self._render_document_reference(ev)

    def _render_web_reference(self, ev: Evidence) -> str:
        ref_id = ev.reference_id or ""
        title = ev.title or "网页来源"
        url = ev.url or "未知"
        snippet = self._trim_snippet(ev.content, 900)
        return f"[{ref_id}] 网页：{title}；链接：{url}\n摘要：{snippet}\n"

    def _render_document_reference(self, ev: Evidence) -> str:
        ref_id = ev.reference_id or ""
        doc_name = ev.title or "文档来源"
        section_path = ev.section_title or "未识别"
        snippet = self._trim_snippet(ev.content, 1100)
        return f"[{ref_id}] 文档：{doc_name}；章节：{section_path}\n内容：{snippet}\n"

    def _trim_snippet(self, snippet: str | None, max_chars: int) -> str:
        if not snippet or not snippet.strip():
            return ""
        if len(snippet) <= max_chars:
            return snippet
        return snippet[:max_chars] + "..."

    @staticmethod
    def _unique_key(ev: Evidence) -> str:
        """构建去重键：
        优先级: parentBlockId > chunkId > url > sourceType+title+snippet
        """
        if ev.chunk_id:
            return f"DOCUMENT:{ev.chunk_id}"
        if ev.url:
            return f"WEB:{ev.url}"
        return f"{ev.source_type}:{ev.title}:{ev.content[:50] if ev.content else ''}"

    @staticmethod
    def _estimate_tokens(char_count: int) -> int:
        return max(1, char_count // 4)

    def _reference_summary(self, ev: Evidence, suffix: str) -> str:
        title = ev.title or ""
        path = ev.section_title or ev.url or ""
        ref_id = str(ev.reference_id) if ev.reference_id is not None else "-"
        path_part = f" | {path}" if path else ""
        return f"[{ref_id}] {title}{path_part} | {suffix}"
