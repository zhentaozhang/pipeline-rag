"""
Supervisor Agent — LLM 问题分解 + SubPlan 生成
"""

import uuid

import structlog
from openai import AsyncOpenAI

from app.chat.schema import ExecutionPlan, SubPlan
from app.common.enums import ExecutionMode
from app.common.llm_client import get_chat_client
from app.orchestrator.subplan import (
    build_sub_plans,
    inherit_plan_scope,
    validate_sub_plans,
)

logger = structlog.get_logger(__name__)

# 复杂/多实体横向对比触发词（命中即建议多任务分解）
_COMPLEX_QUESTION_HINTS = (
    "对比",
    "比较",
    "区别",
    "异同",
    "关联",
    "如何影响",
    "分别",
)


def _should_decompose(plan: ExecutionPlan) -> bool:
    """规则预筛：仅多实体横向对比或极长复合并列问题需要多 Agent 任务分解。

    消除「为什么/原因/分析/总结」等单跳制度解释词导致的严重误报，
    避免在首 token 之前引入无收益的同步 LLM 分解调用。
    """
    question = (plan.rewritten_question or plan.original_question or "").strip()
    if not question:
        return False
    # 多主体横向对比/多任务触发词
    if any(hint in question for hint in _COMPLEX_QUESTION_HINTS):
        return True
    # 极长复合问题（>= 50 字且包含复合并列连词）
    return len(question) >= 50 and any(
        conn in question for conn in ("以及", "并且", "同时", "另外")
    )


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
            _inherit_plan_scope(plan)
            logger.info(
                "supervisor decomposed via graph",
                count=len(graph_sub_plans),
                modes=[sp.mode.value for sp in graph_sub_plans],
            )
            return plan

        if graph_ran:
            logger.warning("supervisor graph rejected sub-plans, keeping single mode")
        return plan

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
            review_status = result.get("review_status")
            if review_status in ("approved", "degraded") and sub_plans:
                for sp in sub_plans:
                    sp.review_status = review_status
                    sp.review_feedback = result.get("feedback", "") or ""
                return sub_plans, True
            return None, True
        except Exception:
            logger.exception("supervisor_graph_decompose_failed")
            return None, False


# 向后兼容与外部测试访问
_inherit_plan_scope = inherit_plan_scope
_build_sub_plans = build_sub_plans
_validate_sub_plans = validate_sub_plans
