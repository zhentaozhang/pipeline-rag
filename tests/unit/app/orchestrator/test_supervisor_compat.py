"""C2 TDD：SupervisorService.decompose 兼容回归（薄门面）。"""

from app.chat.schema import ExecutionPlan
from app.common.enums import ExecutionMode


def _plan() -> ExecutionPlan:
    # 问题含分析触发词，确保通过 supervisor 规则预筛（P0-1c）
    return ExecutionPlan(
        mode=ExecutionMode.RETRIEVAL,
        original_question="为什么两种配置方式在参数说明上有什么区别",
        rewritten_question="为什么两种配置方式在参数说明上有什么区别",
    )


async def test_decompose_returns_same_plan_when_supervisor_disabled(fake_llm):
    from app.config import get_settings
    from app.orchestrator.supervisor import SupervisorService

    settings = get_settings()
    original = settings.rag.supervisor_enabled
    settings.rag.supervisor_enabled = False
    try:
        plan = _plan()
        svc = SupervisorService()
        result = await svc.decompose(plan)
        assert result is plan
    finally:
        settings.rag.supervisor_enabled = original


async def test_decompose_falls_back_when_mode_not_supported(fake_llm):
    """模式不匹配（REACT_AGENT）时原样返回。"""
    from app.orchestrator.supervisor import SupervisorService

    plan = ExecutionPlan(
        mode=ExecutionMode.REACT_AGENT,
        original_question="q",
        rewritten_question="q",
    )
    svc = SupervisorService()
    result = await svc.decompose(plan)
    assert result is plan


async def test_decompose_returns_plan_when_llm_fails(fake_llm):
    """图路径 LLM 失败（无响应）→ 图内部兜底 rejected → 直接保持单模式，plan 不被破坏。"""
    from app.orchestrator.supervisor import SupervisorService

    plan = _plan()
    svc = SupervisorService()
    result = await svc.decompose(plan)
    assert result is plan
    assert not result.supervisor_mode


async def test_decompose_applies_sub_plans_from_graph(fake_llm):
    """图成功时，supervisor_mode/sub_plans/mode 正确写入 plan。"""
    from app.orchestrator.supervisor import SupervisorService

    fake_llm.queue_json(
        {
            "decompose": True,
            "reasoning": "ok",
            "sub_plans": [
                {"id": "1", "mode": "RETRIEVAL", "question": "子问题1", "depends_on": []},
                {"id": "2", "mode": "REACT_AGENT", "question": "子问题2", "depends_on": ["1"]},
            ],
        }
    )
    fake_llm.queue_json({"approved": True, "feedback": "无"})

    plan = _plan()
    svc = SupervisorService()
    result = await svc.decompose(plan)
    assert result.supervisor_mode is True
    assert result.mode == ExecutionMode.MULTI_AGENT
    assert len(result.sub_plans) == 2
    assert result.aggregation_style == "synthesize"
    assert result.sub_plans[0].review_status == "approved"
    assert result.sub_plans[0].review_feedback == "无"


async def test_decompose_supports_rag_chat_mode(fake_llm):
    """RAG_CHAT 模式同样可走图分解。"""
    from app.orchestrator.supervisor import SupervisorService

    fake_llm.queue_json(
        {
            "decompose": True,
            "reasoning": "ok",
            "sub_plans": [
                {"id": "1", "mode": "RETRIEVAL", "question": "子问题1", "depends_on": []},
                {"id": "2", "mode": "REACT_AGENT", "question": "子问题2", "depends_on": ["1"]},
            ],
        }
    )
    fake_llm.queue_json({"approved": True, "feedback": ""})

    plan = ExecutionPlan(
        mode=ExecutionMode.RAG_CHAT,
        original_question="为什么两种方案在实施步骤上有区别",
        rewritten_question="为什么两种方案在实施步骤上有区别",
    )
    svc = SupervisorService()
    result = await svc.decompose(plan)
    assert result is plan
    assert result.supervisor_mode is True
    assert result.mode == ExecutionMode.MULTI_AGENT


async def test_decompose_keeps_single_mode_when_graph_rejects(fake_llm):
    """图评审驳回且重试耗尽时，直接保持单模式返回，不二次跑 legacy（LLM 调用不扩大）。"""
    from app.orchestrator.supervisor import SupervisorService

    # 图路径：decompose ×3 + review ×3（max_review_retries=2 耗尽）
    for _ in range(3):
        fake_llm.queue_json(
            {
                "decompose": True,
                "reasoning": "ok",
                "sub_plans": [
                    {"id": "1", "mode": "RETRIEVAL", "question": "子问题1", "depends_on": []},
                    {"id": "2", "mode": "RETRIEVAL", "question": "子问题1重复", "depends_on": []},
                ],
            }
        )
        fake_llm.queue_json({"approved": False, "feedback": "子问题重复"})
    plan = _plan()
    svc = SupervisorService()
    result = await svc.decompose(plan)
    assert result is plan
    assert not result.supervisor_mode
    # 耗尽后直接返回：LLM 调用恰好 6 次（3 分解 + 3 评审），未触发 legacy 二次循环
    assert len(fake_llm.calls) == 6


async def test_rule_prefilter_skips_simple_question(fake_llm):
    """P0-1c：简单问题（无触发词、非复合）不触发 LLM 分解，零 LLM 调用。"""
    from app.config import get_settings
    from app.orchestrator.supervisor import SupervisorService

    settings = get_settings()
    original = settings.rag.supervisor_rule_prefilter
    settings.rag.supervisor_rule_prefilter = True
    try:
        plan = ExecutionPlan(
            mode=ExecutionMode.RETRIEVAL,
            original_question="如何配置数据库连接",
            rewritten_question="如何配置数据库连接",
        )
        svc = SupervisorService()
        result = await svc.decompose(plan)
        assert result is plan
        assert not result.supervisor_mode
        assert fake_llm.calls == []  # 未触发任何 LLM 调用
    finally:
        settings.rag.supervisor_rule_prefilter = original


async def test_rule_prefilter_allows_complex_question(fake_llm):
    """P0-1c：含分析触发词的复合问题仍然触发分解。"""
    from app.config import get_settings
    from app.orchestrator.supervisor import SupervisorService

    settings = get_settings()
    original = settings.rag.supervisor_rule_prefilter
    settings.rag.supervisor_rule_prefilter = True
    try:
        fake_llm.queue_json(
            {
                "decompose": True,
                "reasoning": "ok",
                "sub_plans": [
                    {"id": "1", "mode": "RETRIEVAL", "question": "子问题1", "depends_on": []},
                    {"id": "2", "mode": "RETRIEVAL", "question": "子问题2", "depends_on": []},
                ],
            }
        )
        fake_llm.queue_json({"approved": True, "feedback": ""})
        plan = ExecutionPlan(
            mode=ExecutionMode.RETRIEVAL,
            original_question="为什么方案 A 与方案 B 的实施步骤有区别",
            rewritten_question="为什么方案 A 与方案 B 的实施步骤有区别",
        )
        svc = SupervisorService()
        result = await svc.decompose(plan)
        assert result.supervisor_mode is True
        assert len(fake_llm.calls) > 0
    finally:
        settings.rag.supervisor_rule_prefilter = original
