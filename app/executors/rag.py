"""
RAG 知识问答执行器

流程：
RAG 引擎检索 → 无证据短路 → Prompt 组装（含预算控制）→ LLM 流式生成（per-chunk 安全过滤）→ SSE 推送
"""

import json
import random
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.schema import ExecutionPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.common.jinja import jinja_env
from app.common.llm_client import get_chat_client
from app.common.sse import SSEEventType, sse_event
from app.config import get_settings
from app.executors.base import ConversationExecutor
from app.executors.rag_stream import extract_text, run_output_filter, stream_llm_with_tools
from app.observability import SpanKind
from app.rag.assembly import PromptAssemblyService
from app.rag.engine import RagRetrievalEngine

logger = structlog.get_logger(__name__)
settings = get_settings()


class QualityResult:
    def __init__(
        self,
        passed: bool,
        score: float,
        issues: list[str],
        suggestion: str = "",
        dimensions: dict[str, float] | None = None,
    ):
        self.passed = passed
        self.score = score
        self.issues = issues
        self.suggestion = suggestion
        self.dimensions = dimensions or {}

    @property
    def feedback(self) -> str:
        parts = []
        if self.issues:
            parts.append("存在的问题：\n" + "\n".join(f"- {i}" for i in self.issues))
        if self.suggestion:
            parts.append(f"改进建议：{self.suggestion}")
        return "\n\n".join(parts)


class AnswerQualityChecker:
    def __init__(self) -> None:
        self._jinja = jinja_env
        self._openai = get_chat_client()

    async def check(
        self,
        question: str,
        answer: str,
        reference_titles: list[str] | None = None,
    ) -> QualityResult:
        if not settings.rag.quality_enabled:
            return QualityResult(passed=True, score=10.0, issues=[])

        prompt = self._build_prompt(question, answer)
        try:
            result_dict = await self._call_llm(prompt)
        except Exception as e:
            logger.warning("quality_check_failed", error=str(e))
            return QualityResult(passed=True, score=10.0, issues=[])

        score = float(result_dict.get("score", 10))
        issues = result_dict.get("issues", [])
        suggestion = result_dict.get("suggestion", "")
        dimensions = result_dict.get("dimensions", {})
        passed = score >= settings.rag.quality_min_score

        if not passed:
            logger.info(
                "quality_check_rejected",
                score=score,
                issues=issues,
                suggestion=suggestion,
            )

        return QualityResult(
            passed=passed,
            score=score,
            issues=issues,
            suggestion=suggestion,
            dimensions=dimensions,
        )

    def _build_prompt(self, question: str, answer: str) -> str:
        template = self._jinja.get_template("quality_check.j2")
        return template.render(question=question, answer=answer)

    async def _call_llm(self, prompt: str) -> dict[str, Any]:
        response = await self._openai.chat.completions.create(
            model=settings.rag.quality_model or settings.llm.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是回答质量审核员。严格按 JSON 格式输出评分结果。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=500,
            timeout=15,
        )
        content = response.choices[0].message.content or "{}"

        json_str = content.strip()
        if json_str.startswith("```"):
            json_str = json_str.split("\n", 1)[-1]
            json_str = json_str.rsplit("```", 1)[0]
        json_str = json_str.strip()

        return json.loads(json_str)


class RagChatExecutor(ConversationExecutor):
    """
    RAG 知识问答执行器。
    走 RAG 检索 → 无证据短路 → Prompt 组装 → LLM 流式生成（SSE 推送）→ 结果融合
    """

    mode = ExecutionMode.RETRIEVAL

    def __init__(self, db: AsyncSession, task: ChatTaskInfo) -> None:
        self.db = db
        self.task = task

    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        tracer = self.task.tracer
        self.task.thinking_steps.append("正在根据问题规划知识检索范围。")
        yield self._emit(SSEEventType.THINKING, "正在根据问题规划知识检索范围。")

        async with tracer.span("rag_retrieve", kind=SpanKind.RETRIEVAL):
            engine = RagRetrievalEngine(db=self.db)
            sub_evidences = await engine.retrieve_with_correction(plan, tracer=self.task.tracer)
            sub_question_list = sub_evidences.sub_question_evidence_list

            used_channels = sub_evidences.used_channels
            retrieval_notes = sub_evidences.retrieval_notes

        for note in retrieval_notes:
            self.task.thinking_steps.append(note)
            yield self._emit(SSEEventType.THINKING, note)

        self.task.used_tools.extend(used_channels)
        if self.task.debug_trace:
            self.task.debug_trace.retrieval_notes = retrieval_notes
            self.task.debug_trace.used_channels = list(used_channels)
            docs = []
            for sq in sub_question_list:
                for ev in sq.evidences:
                    if ev.content:
                        docs.append(ev.content)
            self.task.debug_trace.retrieval_docs = docs

        if sub_evidences.is_empty:
            self.task.thinking_steps.append("当前没有足够证据，直接返回无证据兜底回复。")
            yield self._emit(SSEEventType.THINKING, "当前没有足够证据，直接返回无证据兜底回复。")
            yield self._emit(SSEEventType.TEXT, plan.no_evidence_reply)
            return

        for se in sub_question_list:
            for ev in se.evidences:
                self.task.references.append(
                    {
                        "id": ev.reference_id,
                        "title": ev.title,
                        "source_type": ev.source_type,
                        "url": ev.url,
                        "doc_id": ev.doc_id,
                    }
                )

        self.task.thinking_steps.append("证据整理完成，正在基于证据生成回答。")
        yield self._emit(SSEEventType.THINKING, "证据整理完成，正在基于证据生成回答。")

        assembler = PromptAssemblyService()
        async with tracer.span("evidence_budget", kind=SpanKind.RETRIEVAL):
            prompt_result = assembler.assemble(plan, sub_question_list)
            if self.task.debug_trace:
                self.task.debug_trace.rag_system_prompt = prompt_result.system_prompt
                self.task.debug_trace.rag_user_prompt = prompt_result.user_prompt

        _answer_blocked = False
        async with tracer.span("answer_generate", kind=SpanKind.LLM):
            start_ts = time.time()
            async for chunk in stream_llm_with_tools(
                self.task, prompt_result.system_prompt, prompt_result.user_prompt, self._emit
            ):
                if self.task.first_response_time_ms == 0:
                    elapsed = int((time.time() - start_ts) * 1000)
                    self.task.try_set_first_response_time(elapsed)
                self.task.answer_buffer.append(extract_text(chunk))
                yield chunk

            # ── Post-hoc OutputFilter 全量安全检测 ────────────────────────────
            full_answer = "".join(self.task.answer_buffer)
            output_result = await run_output_filter(full_answer)
            _answer_blocked = not output_result.safe
            if _answer_blocked:
                logger.warning(
                    "rag_answer_blocked_by_output_filter",
                    reason=output_result.reason,
                )
                blocked = output_result.blocked_text
                self.task.answer_buffer.clear()
                self.task.answer_buffer.append(blocked)
                yield sse_event(SSEEventType.STATUS, "⏹ 回答已被安全机制拦截")
                yield sse_event(
                    SSEEventType.ERROR,
                    blocked,
                    conversation_id=self.task.conversation_id,
                    exchange_id=self.task.exchange_id,
                )

        # ── 回答质量审核（自审 + 可选重生成）─────────────────────────
        if not _answer_blocked:
            quality_checker = AnswerQualityChecker()
            quality_result = await quality_checker.check(
                question=plan.original_question,
                answer="".join(self.task.answer_buffer),
                reference_titles=[r.get("title", "") for r in self.task.references],
            )

            while (
                not quality_result.passed and plan.review_round < settings.rag.quality_max_retries
            ):
                plan.review_round += 1
                self.task.thinking_steps.append(
                    f"回答质量审核未通过（得分 {quality_result.score}），"
                    f"正在进行第 {plan.review_round} 轮优化。"
                )
                yield self._emit(
                    SSEEventType.REVIEW,
                    {
                        "round": plan.review_round,
                        "maxRounds": settings.rag.quality_max_retries,
                        "score": quality_result.score,
                        "message": f"回答质量审核未通过（得分 {quality_result.score}），"
                        f"正在进行第 {plan.review_round} 轮优化。",
                    },
                )

                improved_system = (
                    prompt_result.system_prompt
                    + "\n\n## 前一轮回答的问题\n"
                    + quality_result.feedback
                )

                self.task.answer_buffer.clear()
                async for chunk in stream_llm_with_tools(
                    self.task, improved_system, prompt_result.user_prompt, self._emit
                ):
                    self.task.answer_buffer.append(extract_text(chunk))
                    yield chunk

                retry_output = await run_output_filter("".join(self.task.answer_buffer))
                if not retry_output.safe:
                    blocked = retry_output.blocked_text
                    self.task.answer_buffer.clear()
                    self.task.answer_buffer.append(blocked)
                    yield sse_event(SSEEventType.STATUS, "⏹ 回答已被安全机制拦截")
                    yield sse_event(
                        SSEEventType.ERROR,
                        blocked,
                        conversation_id=self.task.conversation_id,
                        exchange_id=self.task.exchange_id,
                    )
                    break

                quality_result = await quality_checker.check(
                    question=plan.original_question,
                    answer="".join(self.task.answer_buffer),
                    reference_titles=[r.get("title", "") for r in self.task.references],
                )

            yield self._emit(
                SSEEventType.REVIEW_RESULT,
                {
                    "passed": quality_result.passed,
                    "score": quality_result.score,
                    "message": (
                        "系统对当前回答的质量置信度较低，建议核实关键信息。"
                        if not quality_result.passed
                        else None
                    ),
                },
            )

            if (
                settings.rag.evaluation_enabled
                and not _answer_blocked
                and random.random() < settings.rag.evaluation_sample_rate
            ):
                try:
                    contexts_list: list[str] = []
                    for sq in sub_question_list:
                        for ev in sq.evidences:
                            if ev.content:
                                contexts_list.append(ev.content)
                    self.task._pending_eval = {
                        "question": plan.original_question,
                        "answer": "".join(self.task.answer_buffer),
                        "contexts": contexts_list,
                    }
                except Exception:
                    logger.exception("rag_eval_params_failed")
