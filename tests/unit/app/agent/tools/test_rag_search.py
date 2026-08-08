"""C1 缺口：Agent 工具 rag_search 也应使用矫正检索（retrieve_with_correction）。"""

from app.chat.schema import Evidence, SubQuestion, SubQuestionEvidence
from app.rag.engine import RagRetrievalContext


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
        title="文档标题",
        content="证据内容A",
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


async def test_rag_search_uses_corrective_retrieval(fake_llm, monkeypatch):
    """证据为空时 rag_search 应通过矫正检索获得证据，而不是直接返回空。"""
    from app.agent.tools.rag_search import rag_search
    from app.rag.engine import RagRetrievalEngine

    calls: list[str] = []

    async def fake_retrieve_with_correction(self, plan, tracer=None):
        calls.append("retrieve_with_correction")
        return _nonempty_context(plan.original_question)

    async def fake_plain_retrieve(self, plan, tracer=None):
        raise AssertionError("应使用 retrieve_with_correction，而不是直接 retrieve")

    monkeypatch.setattr(RagRetrievalEngine, "retrieve_with_correction", fake_retrieve_with_correction)
    monkeypatch.setattr(RagRetrievalEngine, "retrieve", fake_plain_retrieve)

    result = await rag_search.ainvoke({"query": "FastMCP Depends 用法", "top_k": 5})
    assert calls == ["retrieve_with_correction"]
    assert "证据内容A" in result


async def test_rag_search_empty_after_correction_returns_none_message(fake_llm, monkeypatch):
    """矫正后仍无证据时返回未找到提示，而非崩溃。"""
    from app.agent.tools.rag_search import rag_search
    from app.rag.engine import RagRetrievalEngine

    async def fake_retrieve_with_correction(self, plan, tracer=None):
        return _empty_context(plan.original_question)

    monkeypatch.setattr(RagRetrievalEngine, "retrieve_with_correction", fake_retrieve_with_correction)

    result = await rag_search.ainvoke({"query": "找不到的问题", "top_k": 5})
    assert result == "未找到相关文档内容。"