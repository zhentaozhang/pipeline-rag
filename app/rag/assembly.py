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

    def reset(self, new_total_budget: int | None = None) -> None:
        """重置预算及统计状态，用于上下文超标重新组装"""
        if new_total_budget is not None:
            self.total_budget = max(0, new_total_budget)
        self.remaining_total = self.total_budget
        self.remaining_sub_question = self.per_sub_question_budget
        self.rendered_reference_count = 0
        self.omitted_reference_count = 0
        self.rendered_reference_details.clear()
        self.omitted_reference_details.clear()

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
        estimated_tokens = self._estimate_tokens(system_prompt + user_prompt)
        context_limit = settings.llm.context_window_limit
        actual_limit = int(context_limit * (1.0 - settings.rag.context_window_safety_margin))
        utilization = estimated_tokens / context_limit if context_limit > 0 else 0.0
        CONTEXT_WINDOW_UTILIZATION.set(utilization)

        truncation_count = 0
        while estimated_tokens > actual_limit and budget.total_budget > 500:
            truncation_count += 1
            old_total = budget.total_budget
            new_total = max(500, int(budget.total_budget * 0.7))
            reduction = old_total - new_total
            budget.reset(new_total)
            rendered_reference_keys.clear()
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
            estimated_tokens = self._estimate_tokens(system_prompt + user_prompt)
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

    @classmethod
    def _dedup_evidences(
        cls,
        sub_evidences: list[SubQuestionEvidence],
    ) -> tuple[list[SubQuestionEvidence], dict[str, int]]:
        """跨子问题引用去重 + reference_id 映射。"""
        reference_map: dict[str, int] = {}
        rendered_reference_keys: set[str] = set()
        result: list[SubQuestionEvidence] = []

        for sub_ev in sub_evidences:
            allocated_evidences: list[Evidence] = []

            for ev in sub_ev.evidences:
                unique_key = cls._unique_key(ev)
                ref_key = ev.chunk_id if ev.chunk_id else unique_key
                if unique_key in rendered_reference_keys:
                    ev = ev.model_copy()
                    if ev.reference_id is not None:
                        reference_map[ref_key] = ev.reference_id
                        ev.content = f"请参考引用 [{ev.reference_id}]"
                    else:
                        ev.content = "（内容同上条引用）"
                    allocated_evidences.append(ev)
                    continue

                ev = ev.model_copy()
                if ev.reference_id is not None:
                    reference_map[ref_key] = ev.reference_id
                rendered_reference_keys.add(unique_key)
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

    def _ordered_evidences(self, evidences: list[Evidence], budget: PromptBudget) -> list[Evidence]:
        """P2-7 LongContextReorder：预算充足时把最相关证据放到首尾。

        若整组证据放不进当前可用预算（会发生截断/省略），则保持原相关度顺序——
        确保截断仍优先丢弃**最不相关**的尾部，而不是被重排挤到末尾的次相关项。
        """
        if not getattr(settings.rag, "long_context_reorder_enabled", False) or len(evidences) < 3:
            return evidences
        from app.rag.reorder import reorder_long_context

        ordered = reorder_long_context(evidences)
        available = min(budget.remaining_total, budget.remaining_sub_question)
        estimated = sum(len(self._render_reference_block(ev)) for ev in ordered)
        if estimated > available:
            return evidences
        return ordered

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

        for ev in self._ordered_evidences(evidences, budget):
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
                # 软窗口降级尝试：若剩余可用预算 >= 250，尝试以子块为锚点裁剪软窗口，而不是直接丢弃
                available = min(budget.remaining_total, budget.remaining_sub_question)
                consumed = False
                if available >= 250:
                    header = (
                        self._web_header(ev)
                        if ev.source_type == "web"
                        else self._document_header(ev)
                    )
                    max_content_len = available - len(header) - 10
                    if max_content_len >= 150:
                        anchor = getattr(ev, "child_chunk_text", None)
                        soft_content = self._extract_soft_window(
                            ev.content or "", anchor, max_content_len
                        )
                        soft_block = f"{header}{soft_content}\n"
                        if budget.try_consume(len(soft_block)):
                            builder.append(soft_block)
                            rendered_keys.add(unique_key)
                            budget.mark_rendered(
                                self._reference_summary(ev, "已通过软窗口裁剪纳入 Prompt")
                            )
                            consumed = True

                if not consumed:
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
        snippet = self._trim_snippet(ev.content, 900)
        return f"{self._web_header(ev)}{snippet}\n"

    @staticmethod
    def _section_label(ev: Evidence) -> str:
        """拼装章节展示串：路径 + 叶子标题（叶子已在路径里则不重复）。"""
        path = (ev.section_path or "").strip()
        leaf = (ev.section_title or "").strip()
        if path and leaf and leaf not in path:
            return f"{path} › {leaf}"
        return path or leaf

    def _document_header(self, ev: Evidence) -> str:
        """文档引用块 header（完整渲染与软窗口裁剪共用同一实现）。"""
        ref_id = ev.reference_id or ""
        doc_name = ev.document_name or ev.title or "文档来源"
        section = self._section_label(ev) or "未识别"
        return f"[{ref_id}] 文档：{doc_name}；章节：{section}\n内容："

    @staticmethod
    def _web_header(ev: Evidence) -> str:
        ref_id = ev.reference_id or ""
        title = ev.title or "网页来源"
        url = ev.url or "未知"
        return f"[{ref_id}] 网页：{title}；链接：{url}\n摘要："

    def _render_document_reference(self, ev: Evidence) -> str:
        snippet = self._trim_snippet(
            ev.content, getattr(settings.rag, "reference_snippet_max_chars", 2000)
        )
        return f"{self._document_header(ev)}{snippet}\n"

    def _extract_soft_window(self, content: str, anchor: str | None, max_chars: int) -> str:
        """围绕核心锚点（如子块文本）截取软窗口上下文，避免整块截断丢失关键事实。"""
        if not content:
            return ""
        if len(content) <= max_chars:
            return content
        if not anchor or anchor not in content:
            return content[:max_chars] + "..."

        anchor_pos = content.find(anchor)
        anchor_len = len(anchor)
        half_window = (max_chars - anchor_len) // 2

        if half_window <= 0:
            return anchor[:max_chars] + "..."

        start = max(0, anchor_pos - half_window)
        end = min(len(content), start + max_chars)
        if end == len(content):
            start = max(0, end - max_chars)

        window_text = content[start:end]
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return f"{prefix}{window_text}{suffix}"

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
        if getattr(ev, "parent_block_id", None) is not None:
            return f"PARENT:{ev.parent_block_id}"
        if ev.chunk_id:
            return f"DOCUMENT:{ev.chunk_id}"
        if ev.url:
            return f"WEB:{ev.url}"
        return f"{ev.source_type}:{ev.title}:{ev.content[:50] if ev.content else ''}"

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """估算 token 数：复用 CJK 感知口径（中文≈1/1.5 token/字，ASCII≈1/4）。

        旧实现 ``chars // 4`` 是英文口径，对中文低估约 3~4 倍，
        会让 CONTEXT_WINDOW_UTILIZATION 与上下文溢出保护失真。
        """
        from app.chat.service_utils import _estimate_tokens as _estimate

        return max(1, _estimate(text or ""))

    def _reference_summary(self, ev: Evidence, suffix: str) -> str:
        title = ev.document_name or ev.title or ""
        path = self._section_label(ev) or ev.url or ""
        ref_id = str(ev.reference_id) if ev.reference_id is not None else "-"
        path_part = f" | {path}" if path else ""
        return f"[{ref_id}] {title}{path_part} | {suffix}"
