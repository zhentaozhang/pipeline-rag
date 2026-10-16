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


async def test_rule_prefilter_skips_single_hop_institutional_questions(fake_llm):
    """审查报告 R10：制度解释类单跳问题不得误触发 LLM 任务分解。"""
    from app.config import get_settings
    from app.orchestrator.supervisor import SupervisorService

    settings = get_settings()
    original = settings.rag.supervisor_rule_prefilter
    settings.rag.supervisor_rule_prefilter = True
    try:
        svc = SupervisorService()
        for q in ("为什么报销需要发票", "总结一下差旅制度", "分析一下这个流程"):
            plan = ExecutionPlan(
                mode=ExecutionMode.RETRIEVAL,
                original_question=q,
                rewritten_question=q,
            )
            result = await svc.decompose(plan)
            assert result.supervisor_mode is False
        assert fake_llm.calls == []  # 零 LLM 调用
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


async def test_decompose_propagates_route_scope_to_sub_plans(fake_llm):
    """回归（审查报告 D3）：子计划必须继承父计划的路由范围与导航决策。

    `_build_sub_plans` 只从 LLM JSON 取 id/mode/question/depends_on，
    `SubPlan.doc_ids` 恒为空；ParallelExecutor 又用它构造 worker 计划的
    `retrieval_document_ids` —— 并行分支因此绕过知识路由，在全部文档上检索。
    """
    from app.chat.schema import DocumentNavigationDecision
    from app.orchestrator.supervisor import SupervisorService

    fake_llm.queue_json(
        {
            "decompose": True,
            "reasoning": "ok",
            "sub_plans": [
                {"id": "1", "mode": "RETRIEVAL", "question": "子问题1", "depends_on": []},
                {"id": "2", "mode": "RETRIEVAL", "question": "子问题2", "depends_on": ["1"]},
            ],
        }
    )
    fake_llm.queue_json({"approved": True, "feedback": ""})

    plan = _plan()
    plan.retrieval_document_ids = ["11", "22"]
    plan.navigation_decision = DocumentNavigationDecision(execution_mode="GRAPH_ONLY")

    result = await SupervisorService().decompose(plan)

    assert result.supervisor_mode is True
    assert result.mode == ExecutionMode.MULTI_AGENT
    assert len(result.sub_plans) == 2
    for sp in result.sub_plans:
        assert sp.doc_ids == ["11", "22"], "子计划未继承父计划的路由文档范围"
        assert sp.navigation_decision is not None
        assert sp.navigation_decision.execution_mode == "GRAPH_ONLY"


def test_inherit_scope_keeps_explicit_sub_plan_scope():
    """子计划自带范围时不覆盖（LLM 若显式指定，尊重它）。"""
    from app.chat.schema import SubPlan
    from app.orchestrator.supervisor import _inherit_plan_scope

    plan = _plan()
    plan.supervisor_mode = True
    plan.retrieval_document_ids = ["11"]
    plan.sub_plans = [
        SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q", doc_ids=["99"]),
    ]

    _inherit_plan_scope(plan)
    assert plan.sub_plans[0].doc_ids == ["99"]


def test_inherit_scope_skipped_when_not_multi_agent():
    """评审耗尽后残留的 rejected 子计划不会被执行，不应继承范围。"""
    from app.chat.schema import SubPlan
    from app.orchestrator.supervisor import _inherit_plan_scope

    plan = _plan()
    plan.supervisor_mode = False  # 保持单模式
    plan.retrieval_document_ids = ["11"]
    plan.sub_plans = [SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q")]

    _inherit_plan_scope(plan)
    assert plan.sub_plans[0].doc_ids == []


def test_validate_sub_plans_detects_cycles():
    """审查报告 R13：_validate_sub_plans 必须在计划期拦截循环依赖。"""
    from app.chat.schema import SubPlan
    from app.orchestrator.supervisor import _validate_sub_plans

    # A -> B, B -> A
    cyclic_plans = [
        SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=["2"]),
        SubPlan(id="2", mode=ExecutionMode.RETRIEVAL, question="q2", depends_on=["1"]),
    ]
    valid, errors = _validate_sub_plans(cyclic_plans)
    assert valid is False
    assert any("循环依赖" in err for err in errors)

    # 正常无环依赖
    acyclic_plans = [
        SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=[]),
        SubPlan(id="2", mode=ExecutionMode.RETRIEVAL, question="q2", depends_on=["1"]),
    ]
    valid, errors = _validate_sub_plans(acyclic_plans)
    assert valid is True
    assert errors == []
