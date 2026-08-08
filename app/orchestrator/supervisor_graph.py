"""LangGraph supervisor 图：decompose → validate → review 循环。

替代 SupervisorService 手写 LLM 分解/评审循环，由框架持有状态与循环控制。
LLM 调用保持走 get_chat_client()（复用 llm_breaker + 现有模板），
因此 fake_llm 可确定性注入响应做测试。
"""

from __future__ import annotations

import json
from typing import TypedDict

import structlog

from app.chat.schema import ExecutionPlan, SubPlan
from app.common.jinja import jinja_env
from app.common.llm_client import get_chat_client, llm_breaker
from app.config import get_settings
from app.orchestrator.supervisor import _build_sub_plans, _validate_sub_plans

logger = structlog.get_logger(__name__)


class SupervisorState(TypedDict, total=False):
    plan: ExecutionPlan
    sub_plans: list[SubPlan] | None
    feedback: str
    review_status: str | None
    review_retries: int


async def decompose_node(state: SupervisorState) -> dict:
    """LLM 分解：把问题分解为 sub_plans（复用 supervisor_decompose.j2）。"""
    plan: ExecutionPlan = state["plan"]
    settings = get_settings()
    client = get_chat_client()
    template = jinja_env.get_template("supervisor_decompose.j2")
    prompt = template.render(
        question=plan.original_question,
        history_summary=plan.history_summary or "",
        feedback=state.get("feedback", ""),
    )
    try:
        async with llm_breaker():
            response = await client.chat.completions.create(
                model=settings.llm.model,
                messages=[
                    {"role": "system", "content": "你是智能任务分解助手。仅输出 JSON。"},
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
        return {"sub_plans": None}

    if not result.get("decompose"):
        return {"sub_plans": None}

    raw_plans = result.get("sub_plans", [])
    if not raw_plans or len(raw_plans) < 2:
        return {"sub_plans": None}

    sub_plans = _build_sub_plans(raw_plans)
    if not sub_plans:
        return {"sub_plans": None}
    return {"sub_plans": sub_plans}


async def validate_node(state: SupervisorState) -> dict:
    """结构验证：依赖引用有效、无重复 ID、问题非空（复用 supervisor._validate_sub_plans）。"""
    sub_plans = state.get("sub_plans")
    if not sub_plans:
        return {"review_status": "rejected", "sub_plans": None}
    is_valid, _errors = _validate_sub_plans(sub_plans)
    if not is_valid:
        return {"review_status": "rejected", "sub_plans": None}
    return {"review_status": "approved"}


async def review_node(state: SupervisorState) -> dict:
    """LLM 质量评审（复用 supervisor_review.j2）；失败兜底 approved。"""
    sub_plans = state.get("sub_plans")
    if not sub_plans:
        return {"review_status": "approved"}
    plan: ExecutionPlan = state["plan"]
    settings = get_settings()
    client = get_chat_client()
    template = jinja_env.get_template("supervisor_review.j2")
    prompt = template.render(question=plan.original_question, sub_plans=sub_plans)
    try:
        async with llm_breaker():
            response = await client.chat.completions.create(
                model=settings.llm.model,
                messages=[
                    {"role": "system", "content": "你是质量评审助手。仅输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=512,
                response_format={"type": "json_object"},
                timeout=15,
            )
        content = response.choices[0].message.content or "{}"
        result = json.loads(content)
    except Exception:
        logger.exception("sub_plan_review_failed")
        return {"review_status": "approved"}

    approved = result.get("approved", True)
    feedback = result.get("feedback", "") or ""
    if approved:
        return {"review_status": "approved", "feedback": feedback}
    retries = state.get("review_retries", 0) + 1
    return {"review_status": "rejected", "feedback": feedback, "review_retries": retries}


def _route_after_validate(state: SupervisorState) -> str:
    return "ok" if state.get("review_status") == "approved" else "fail"


def _route_after_review(state: SupervisorState) -> str:
    """approved → END；rejected 且重试未耗尽 → retry 回 decompose；否则 → END。

    与 legacy 语义一致（range(max_review_retries + 1) 次评审）：
    rejected 且 review_retries <= max 时还有重试机会。
    """
    if state.get("review_status") == "approved":
        return "approved"
    retries_used = state.get("review_retries", 0)
    settings = get_settings()
    if retries_used <= settings.rag.supervisor_max_review_retries:
        return "retry"
    return "rejected"


def build_supervisor_graph():
    """构建并编译 supervisor 图；supervisor_enabled=False 时返回 None。"""
    settings = get_settings()
    if not settings.rag.supervisor_enabled:
        return None

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    workflow = StateGraph(SupervisorState)
    workflow.add_node("decompose", decompose_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("review", review_node)

    workflow.add_edge(START, "decompose")
    workflow.add_edge("decompose", "validate")
    workflow.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"ok": "review", "fail": END},
    )
    workflow.add_conditional_edges(
        "review",
        _route_after_review,
        {"approved": END, "retry": "decompose", "rejected": END},
    )
    return workflow.compile(checkpointer=InMemorySaver())
