"""C1 Corrective Retrieval：检索证据不足时改写重查。"""


from app.chat.schema import Evidence, ExecutionPlan, SubQuestion, SubQuestionEvidence
from app.common.enums import ExecutionMode
from app.rag.engine import RagRetrievalContext, RagRetrievalEngine


def _make_plan(question: str = "什么是 FastMCP 的 Depends 用法？") -> ExecutionPlan:
    return ExecutionPlan(
        mode=ExecutionMode.RETRIEVAL,
        original_question=question,
        rewritten_question=question,
        sub_questions=[],
    )


def _empty_context(question: str) -> RagRetrievalContext:
    se = SubQuestionEvidence(sub_question=SubQuestion(index=0, text=question), evidences=[])
    return RagRetrievalContext(
        retrieval_question=question,
        sub_question_evidence_list=[se],
    )


def _nonempty_context(question: str) -> RagRetrievalContext:
    ev = Evidence(
        chunk_id="c1",
        doc_id="d1",
        title="t",
        content="证据内容",
        score=0.9,
        original_score=0.9,
    )
    se = SubQuestionEvidence(
        sub_question=SubQuestion(index=0, text=question), evidences=[ev]
    )
    return RagRetrievalContext(
        retrieval_question=question,
        sub_question_evidence_list=[se],
    )


async def test_sufficient_evidence_no_rewrite(fake_llm, monkeypatch):
    """证据充足时不应触发改写重查（fake LLM 空队列会抛异常，可作哨兵）。"""
    plan = _make_plan()
    engine = RagRetrievalEngine()

    async def fake_retrieve(plan, tracer=None):
        return _nonempty_context(plan.original_question)

    monkeypatch.setattr(engine, "retrieve", fake_retrieve)

    ctx = await engine.retrieve_with_correction(plan)
    assert ctx.is_empty is False
    assert fake_llm.calls == [], "证据充足时不应调用改写 LLM"


async def test_empty_evidence_triggers_rewrite(fake_llm, monkeypatch):
    """证据为空时应改写查询并重查一次。"""
    plan = _make_plan()
    engine = RagRetrievalEngine()

    calls: list[str] = []

    async def fake_retrieve(plan, tracer=None):
        q = plan.original_question
        calls.append(q)
        # 第一次空，第二次非空
        if len(calls) == 1:
            return _empty_context(q)
        return _nonempty_context(q)

    monkeypatch.setattr(engine, "retrieve", fake_retrieve)
    fake_llm.queue_json({"rewrite": "API key 的 Depends 用法", "should_split": False, "sub_questions": []})

    ctx = await engine.retrieve_with_correction(plan)
    assert len(calls) == 2, "应触发一次重查"
    assert fake_llm.calls, "应调用改写 LLM"
    assert ctx.is_empty is False
    assert any("重查" in n for n in ctx.retrieval_notes)


async def test_corrective_retrieval_disabled(fake_llm, monkeypatch):
    """配置关闭时不做矫正。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings.rag, "corrective_retrieval_enabled", False)

    plan = _make_plan()
    engine = RagRetrievalEngine()

    async def fake_retrieve(plan, tracer=None):
        return _empty_context(plan.original_question)

    monkeypatch.setattr(engine, "retrieve", fake_retrieve)
    ctx = await engine.retrieve_with_correction(plan)
    assert ctx.is_empty is True
    assert fake_llm.calls == [], "关闭矫正后不应调用改写 LLM"
    assert fake_llm.calls == []


async def test_rewrite_failure_keeps_empty(fake_llm, monkeypatch):
    """改写失败时保持原结果，不崩溃。"""
    plan = _make_plan()
    engine = RagRetrievalEngine()

    async def fake_retrieve(plan, tracer=None):
        return _empty_context(plan.original_question)

    monkeypatch.setattr(engine, "retrieve", fake_retrieve)
    # 不注入响应 → 改写抛异常 → _rewrite_query 捕获返回 ""
    ctx = await engine.retrieve_with_correction(plan)
    assert ctx.is_empty is True


async def test_max_rounds_limits_rewrites(fake_llm, monkeypatch):
    """证据持续为空时最多改写 max_rounds 次，不无限循环。"""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings.rag, "corrective_retrieval_max_rounds", 2)

    plan = _make_plan()
    engine = RagRetrievalEngine()
    calls = []

    async def fake_retrieve(plan, tracer=None):
        calls.append(plan.original_question)
        return _empty_context(plan.original_question)

    monkeypatch.setattr(engine, "retrieve", fake_retrieve)
    fake_llm.set_fallback(
        lambda kwargs: '{"rewrite": "改写查询B", "should_split": false, "sub_questions": []}'
    )

    ctx = await engine.retrieve_with_correction(plan)
    assert ctx.is_empty is True
    assert len(calls) == 3, "初始 1 次 + 最多 2 轮改写重查"


async def test_rewrite_same_query_no_retry(fake_llm, monkeypatch):
    """改写结果与原文相同时不重复检索。"""
    plan = _make_plan("已完整清晰的问题")
    engine = RagRetrievalEngine()
    calls = []

    async def fake_retrieve(plan, tracer=None):
        calls.append(plan.original_question)
        return _empty_context(plan.original_question)

    monkeypatch.setattr(engine, "retrieve", fake_retrieve)
    fake_llm.queue_json(
        {"rewrite": "已完整清晰的问题", "should_split": False, "sub_questions": []}
    )

    ctx = await engine.retrieve_with_correction(plan)
    assert ctx.is_empty is True
    assert len(calls) == 1, "改写无变化时不重查"