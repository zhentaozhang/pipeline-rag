"""C2 TDD：supervisor 图（decompose→validate→review 循环）。"""

from app.chat.schema import ExecutionPlan
from app.common.enums import ExecutionMode


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        mode=ExecutionMode.RETRIEVAL,
        original_question="测试问题",
        rewritten_question="测试问题",
    )


async def test_graph_returns_compiled_graph(fake_llm):
    from app.orchestrator.supervisor_graph import build_supervisor_graph

    graph = build_supervisor_graph()
    assert hasattr(graph, "ainvoke") or hasattr(graph, "invoke")


async def test_graph_disabled_returns_none(fake_llm):
    from app.config import get_settings
    from app.orchestrator.supervisor_graph import build_supervisor_graph

    settings = get_settings()
    original = settings.rag.supervisor_enabled
    settings.rag.supervisor_enabled = False
    try:
        assert build_supervisor_graph() is None
    finally:
        settings.rag.supervisor_enabled = original


async def test_decompose_node_builds_sub_plans(fake_llm):
    """LLM 返回合法分解 JSON 时，decompose_node 产出 SubPlan 列表。"""
    from app.orchestrator.supervisor_graph import SupervisorState, decompose_node

    fake_llm.queue_json(
        {
            "decompose": True,
            "reasoning": "需要两个维度",
            "sub_plans": [
                {"id": "1", "mode": "RETRIEVAL", "question": "子问题1", "depends_on": []},
                {"id": "2", "mode": "REACT_AGENT", "question": "子问题2", "depends_on": ["1"]},
            ],
        }
    )

    state: SupervisorState = {"plan": _plan(), "feedback": ""}
    result = await decompose_node(state)
    sub_plans = result["sub_plans"]
    assert len(sub_plans) == 2
    assert sub_plans[0].id == "1"
    assert sub_plans[0].mode == ExecutionMode.RETRIEVAL
    assert sub_plans[1].depends_on == ["1"]


async def test_decompose_node_returns_none_when_llm_declines(fake_llm):
    from app.orchestrator.supervisor_graph import SupervisorState, decompose_node

    fake_llm.queue_json({"decompose": False})
    state: SupervisorState = {"plan": _plan(), "feedback": ""}
    result = await decompose_node(state)
    assert result["sub_plans"] is None


async def test_validate_node_rejects_bad_deps():
    from app.chat.schema import SubPlan
    from app.orchestrator.supervisor_graph import SupervisorState, validate_node

    state: SupervisorState = {
        "plan": _plan(),
        "sub_plans": [
            SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=["9"]),
        ],
        "feedback": "",
    }
    result = await validate_node(state)
    assert result["review_status"] == "rejected"
    assert result["sub_plans"] is None


async def test_validate_node_accepts_valid_plans():
    from app.chat.schema import SubPlan
    from app.orchestrator.supervisor_graph import SupervisorState, validate_node

    sub_plans = [
        SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=[]),
        SubPlan(id="2", mode=ExecutionMode.REACT_AGENT, question="q2", depends_on=["1"]),
    ]
    state: SupervisorState = {"plan": _plan(), "sub_plans": sub_plans, "feedback": ""}
    result = await validate_node(state)
    assert result["review_status"] == "approved"


async def test_validate_node_rejects_empty_sub_plans():
    from app.orchestrator.supervisor_graph import SupervisorState, validate_node

    state: SupervisorState = {"plan": _plan(), "sub_plans": None, "feedback": ""}
    result = await validate_node(state)
    assert result["review_status"] == "rejected"


async def test_review_node_approved(fake_llm):
    from app.chat.schema import SubPlan
    from app.orchestrator.supervisor_graph import SupervisorState, review_node

    fake_llm.queue_json({"approved": True, "feedback": ""})
    state: SupervisorState = {
        "plan": _plan(),
        "sub_plans": [
            SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=[]),
            SubPlan(id="2", mode=ExecutionMode.REACT_AGENT, question="q2", depends_on=["1"]),
        ],
        "feedback": "",
        "review_status": "approved",
    }
    result = await review_node(state)
    assert result["review_status"] == "approved"


async def test_review_node_rejected(fake_llm):
    from app.chat.schema import SubPlan
    from app.orchestrator.supervisor_graph import SupervisorState, review_node

    fake_llm.queue_json({"approved": False, "feedback": "子问题重复"})
    state: SupervisorState = {
        "plan": _plan(),
        "sub_plans": [
            SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=[]),
        ],
        "feedback": "",
        "review_status": "approved",
    }
    result = await review_node(state)
    assert result["review_status"] == "rejected"
    assert result["feedback"] == "子问题重复"
    assert result["review_retries"] == 1


async def test_review_node_falls_back_approved_on_llm_error(fake_llm):
    from app.chat.schema import SubPlan
    from app.orchestrator.supervisor_graph import SupervisorState, review_node

    state: SupervisorState = {
        "plan": _plan(),
        "sub_plans": [
            SubPlan(id="1", mode=ExecutionMode.RETRIEVAL, question="q1", depends_on=[]),
            SubPlan(id="2", mode=ExecutionMode.REACT_AGENT, question="q2", depends_on=["1"]),
        ],
        "feedback": "",
        "review_status": "approved",
    }
    result = await review_node(state)
    assert result["review_status"] == "approved"


async def test_graph_end_to_end_approved(fake_llm):
    """整图：分解→验证→评审通过 → 返回 approved sub_plans。"""
    from app.orchestrator.supervisor_graph import build_supervisor_graph

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

    graph = build_supervisor_graph()
    result = await graph.ainvoke(
        {"plan": _plan(), "feedback": ""},
        config={"configurable": {"thread_id": "t1"}},
    )
    assert result["review_status"] == "approved"
    assert len(result["sub_plans"]) == 2


async def test_graph_retry_then_approved(fake_llm):
    """评审驳回一次后重试分解，第二次 approved。"""
    from app.orchestrator.supervisor_graph import build_supervisor_graph

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
    fake_llm.queue_json(
        {
            "decompose": True,
            "reasoning": "修正后",
            "sub_plans": [
                {"id": "1", "mode": "RETRIEVAL", "question": "子问题1", "depends_on": []},
                {"id": "2", "mode": "REACT_AGENT", "question": "子问题2", "depends_on": []},
            ],
        }
    )
    fake_llm.queue_json({"approved": True, "feedback": ""})

    graph = build_supervisor_graph()
    result = await graph.ainvoke(
        {"plan": _plan(), "feedback": ""},
        config={"configurable": {"thread_id": "t2"}},
    )
    assert result["review_status"] == "approved"
    assert len(result["sub_plans"]) == 2
    assert result["sub_plans"][0].question == "子问题1"
    # 重试的 decompose prompt 必须携带前次评审 feedback（循环闭环的关键）
    # 调用顺序：decompose1(0) → review1(1) → decompose2(2) → review2(3)
    assert len(fake_llm.calls) == 4
    retry_prompt = fake_llm.calls[2]["kwargs"]["messages"][1]["content"]
    assert "子问题重复" in retry_prompt


async def test_graph_review_exhausted_falls_back(fake_llm):
    """评审持续驳回至重试上限 → rejected → END（不进入死循环）。"""
    from app.orchestrator.supervisor_graph import build_supervisor_graph

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

    graph = build_supervisor_graph()
    result = await graph.ainvoke(
        {"plan": _plan(), "feedback": ""},
        config={"configurable": {"thread_id": "t3"}},
    )
    assert result["review_status"] == "rejected"
    assert result["review_retries"] == 3
