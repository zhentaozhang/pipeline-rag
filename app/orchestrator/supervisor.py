"""
Supervisor Agent — LLM 问题分解 + SubPlan 生成
"""

import json
import uuid

import structlog
from openai import AsyncOpenAI

from app.chat.schema import ExecutionPlan, SubPlan
from app.common.enums import ExecutionMode
from app.common.jinja import jinja_env as _jinja_env
from app.common.llm_client import get_chat_client, llm_breaker

logger = structlog.get_logger(__name__)

# P0-1c: 复杂/多跳问题触发词（命中即建议分解）
_COMPLEX_QUESTION_HINTS = (
    "对比",
    "比较",
    "区别",
    "为什么",
    "原因",
    "关系",
    "关联",
    "影响",
    "如何影响",
    "分析",
    "总结",
    "综述",
    "分别",
)


def _should_decompose(plan: ExecutionPlan) -> bool:
    """规则预筛：仅复合问题/分析类/长问题需要 LLM 任务分解。"""
    question = (plan.rewritten_question or plan.original_question or "").strip()
    if not question:
        return False
    # 已拆分为多个子问题的复合问题
    if len(plan.rewrite_sub_questions or []) > 1:
        return True
    # 分析/多跳类触发词
    if any(hint in question for hint in _COMPLEX_QUESTION_HINTS):
        return True
    # 长问题（>= 40 字）大概率是多跳
    return len(question) >= 40


class SupervisorService:
    """LLM 驱动的任务分解服务（薄门面：优先走 LangGraph supervisor 图，失败回退 legacy）"""

    def __init__(self) -> None:
        self._openai: AsyncOpenAI | None = None

    def _get_openai(self) -> AsyncOpenAI:
        if self._openai is None:
            self._openai = get_chat_client()
        return self._openai

    async def decompose(self, plan: ExecutionPlan) -> ExecutionPlan:
        from app.config import get_settings

        settings = get_settings()

        if not settings.rag.supervisor_enabled:
            return plan

        if plan.mode not in (ExecutionMode.RETRIEVAL, ExecutionMode.RAG_CHAT):
            return plan

        # P0-1c: 规则预筛——简单问题不触发 LLM 分解（省一次关键路径 LLM 调用）
        if settings.rag.supervisor_rule_prefilter and not _should_decompose(plan):
            logger.info(
                "supervisor rule prefilter: skip decomposition",
                question=(plan.original_question or "")[:50],
            )
            return plan

        graph_sub_plans, graph_ran = await self._decompose_via_graph(plan)
        if graph_sub_plans is not None:
            plan.supervisor_mode = True
            plan.mode = ExecutionMode.MULTI_AGENT
            plan.sub_plans = graph_sub_plans
            plan.aggregation_style = "synthesize"
            logger.info(
                "supervisor decomposed via graph",
                count=len(graph_sub_plans),
                modes=[sp.mode.value for sp in graph_sub_plans],
            )
            return plan

        if graph_ran:
            # 图明确判定不合格（结构校验失败/评审重试耗尽）：与 legacy 耗尽语义一致，
            # 直接保持单模式返回，不重跑 legacy（避免二次 LLM 成本与结果不确定性）
            logger.warning("supervisor graph rejected sub-plans, keeping single mode")
            return plan

        return await self._decompose_legacy(plan)

    async def _decompose_via_graph(self, plan: ExecutionPlan) -> tuple[list[SubPlan] | None, bool]:
        """调用 LangGraph supervisor 图。

        返回 (sub_plans, graph_ran)：
        - sub_plans 非 None：图评审通过，sub_plans 可直接使用
        - graph_ran=True 且 sub_plans=None：图运行但判定不合格（调用方应直接保持单模式）
        - graph_ran=False：图不可用或异常（调用方应回退 legacy）
        """
        try:
            from app.orchestrator.supervisor_graph import build_supervisor_graph

            graph = build_supervisor_graph()
            if graph is None:
                return None, False
            result = await graph.ainvoke(
                {"plan": plan, "feedback": ""},
                config={"configurable": {"thread_id": f"sup-{uuid.uuid4().hex}"}},
            )
            sub_plans = result.get("sub_plans")
            if result.get("review_status") == "approved" and sub_plans:
                for sp in sub_plans:
                    sp.review_status = "approved"
                    sp.review_feedback = result.get("feedback", "") or ""
                return sub_plans, True
            return None, True
        except Exception:
            logger.exception("supervisor_graph_decompose_failed, falling back to legacy")
            return None, False

    async def _decompose_legacy(self, plan: ExecutionPlan) -> ExecutionPlan:
        """legacy 分解：LLM 分解 + 结构验证 + 评审重试循环（原 decompose 主体）。"""

        from app.config import get_settings

        settings = get_settings()

        try:
            prompt = self._render_prompt(plan)
            client = self._get_openai()
            async with llm_breaker():
                response = await client.chat.completions.create(
                    model=settings.llm.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是智能任务分解助手。仅输出 JSON。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=settings.rag.supervisor_temperature,
                    max_tokens=1024,
                    response_format={"type": "json_object"},
                    timeout=settings.llm.timeout_seconds,
                )
            content = response.choices[0].message.content or "{}"
            result = json.loads(content)
        except Exception:
            logger.exception("supervisor_decompose_failed")
            return plan

        if not result.get("decompose"):
            logger.info("supervisor declined to decompose")
            return plan

        raw_plans = result.get("sub_plans", [])
        if not raw_plans or len(raw_plans) < 2:
            return plan

        sub_plans = _build_sub_plans(raw_plans)
        if not sub_plans:
            return plan

        # ── Phase A: 结构验证 ────────────────────────────────
        is_valid, errors = _validate_sub_plans(sub_plans)
        if not is_valid:
            logger.warning("sub_plan structural validation failed", errors=errors)
            return plan

        # ── Phase A: LLM 质量评审 + 自动重试 ────────────────
        prompt_feedback = ""
        max_retries = settings.rag.supervisor_max_review_retries
        for attempt in range(max_retries + 1):
            if attempt > 0:
                try:
                    prompt = self._render_prompt(plan, feedback=prompt_feedback)
                    client = self._get_openai()
                    async with llm_breaker():
                        response = await client.chat.completions.create(
                            model=settings.llm.model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": "你是智能任务分解助手。仅输出 JSON。",
                                },
                                {"role": "user", "content": prompt},
                            ],
                            temperature=settings.rag.supervisor_temperature,
                            max_tokens=1024,
                            response_format={"type": "json_object"},
                            timeout=settings.llm.timeout_seconds,
                        )
                    content = response.choices[0].message.content or "{}"
                    result = json.loads(content)
                    raw_plans = result.get("sub_plans", [])
                    if not raw_plans or len(raw_plans) < 2:
                        return plan
                    sub_plans = _build_sub_plans(raw_plans)
                    if not sub_plans:
                        return plan
                    is_valid, errors = _validate_sub_plans(sub_plans)
                    if not is_valid:
                        return plan
                except Exception:
                    logger.exception("supervisor_retry_decompose_failed")
                    return plan

            approved, feedback = await self._review_sub_plans(sub_plans, plan.original_question)
            prompt_feedback = feedback
            for sp in sub_plans:
                sp.review_status = "approved" if approved else "rejected"
                sp.review_feedback = feedback
            if approved:
                break
            logger.warning("sub_plan review rejected", attempt=attempt, feedback=feedback)
        else:
            logger.warning("sub_plan review exhausted retries, falling back to single mode")
            for sp in sub_plans:
                sp.review_status = "rejected"
            plan.sub_plans = sub_plans
            return plan

        plan.supervisor_mode = True
        plan.mode = ExecutionMode.MULTI_AGENT
        plan.sub_plans = sub_plans
        plan.aggregation_style = "synthesize"
        logger.info(
            "supervisor decomposed",
            count=len(sub_plans),
            modes=[sp.mode.value for sp in sub_plans],
        )
        return plan

    def _render_prompt(self, plan: ExecutionPlan, feedback: str = "") -> str:
        template = _jinja_env.get_template("supervisor_decompose.j2")
        return template.render(
            question=plan.original_question,
            history_summary=plan.history_summary or "",
            feedback=feedback,
        )

    async def _review_sub_plans(self, sub_plans: list[SubPlan], question: str) -> tuple[bool, str]:
        """LLM 质量评审：检查子任务分解的完整性和合理性。

        返回 (approved, feedback)。
        """
        from app.config import get_settings

        settings = get_settings()
        if not settings.rag.supervisor_enabled:
            return True, ""

        try:
            template = _jinja_env.get_template("supervisor_review.j2")
            prompt = template.render(question=question, sub_plans=sub_plans)
            client = self._get_openai()
            async with llm_breaker():
                response = await client.chat.completions.create(
                    model=settings.llm.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "你是质量评审助手。仅输出 JSON。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=512,
                    response_format={"type": "json_object"},
                    timeout=15,
                )
            content = response.choices[0].message.content or "{}"
            result = json.loads(content)
            approved = result.get("approved", True)
            feedback = result.get("feedback", "") or ""
            return bool(approved), feedback
        except Exception:
            logger.exception("sub_plan_review_failed")
            return True, ""


def _build_sub_plans(raw_plans: list[dict]) -> list[SubPlan]:
    sub_plans: list[SubPlan] = []
    for raw in raw_plans:
        mode_str = raw.get("mode", "RETRIEVAL").upper()
        try:
            mode = ExecutionMode(mode_str)
        except ValueError:
            logger.warning("unknown mode in sub_plan", mode=mode_str)
            continue
        sub_plans.append(
            SubPlan(
                id=raw.get("id", str(len(sub_plans) + 1)),
                mode=mode,
                question=raw.get("question", ""),
                depends_on=raw.get("depends_on", []),
            )
        )
    return sub_plans


def _validate_sub_plans(sub_plans: list[SubPlan]) -> tuple[bool, list[str]]:
    """结构验证：检查依赖引用有效、无重复 ID、问题非空。"""
    errors: list[str] = []
    ids = {sp.id for sp in sub_plans}

    if len(ids) != len(sub_plans):
        errors.append("子计划 ID 存在重复")
        return False, errors

    for sp in sub_plans:
        if not sp.question or not sp.question.strip():
            errors.append(f"子计划 {sp.id} 问题为空")
        for dep_id in sp.depends_on:
            if dep_id not in ids:
                errors.append(f"子计划 {sp.id} 依赖 {dep_id} 不存在")

    return len(errors) == 0, errors
