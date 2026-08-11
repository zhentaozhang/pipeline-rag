"""QueryRewriteStage 信号测试：无需改写时返回 SKIP，需要改写时返回 CONTINUE。"""

import pytest

from app.chat.memory import MemoryContext
from app.common.enums import ChatQueryMode
from app.common.pipeline import StageSignal
from app.orchestrator.context import PrepareContext
from app.orchestrator.query_rewriter import ChatQueryRewriteService, RewriteResult
from app.orchestrator.stages.query_rewrite import QueryRewriteStage


def _ctx(question: str = "这个问题已经足够完整清晰，不需要改写处理") -> PrepareContext:
    return PrepareContext(
        question=question,
        conversation_id="conv-1",
        memory_ctx=MemoryContext(),
        chat_mode=ChatQueryMode.AUTO_DOCUMENT,
    )


class TestQueryRewriteStageSignal:
    async def test_skip_when_no_rewrite_needed(self, monkeypatch):
        """无需改写（needs_rewrite=False）→ SKIP，且不写 ctx。"""

        async def fake_rewrite(self, **kwargs) -> RewriteResult:
            return RewriteResult(rewritten="", sub_questions=[], keywords=[])

        monkeypatch.setattr(ChatQueryRewriteService, "rewrite", fake_rewrite)
        ctx = _ctx()
        result = await QueryRewriteStage().process(ctx)
        assert result.signal == StageSignal.SKIP
        assert ctx.rewritten_question == ""
        assert ctx.rewrite_sub_questions == []

    async def test_continue_when_rewrite_needed(self, monkeypatch):
        """需要改写（needs_rewrite=True）→ CONTINUE，且写入改写结果。"""

        async def fake_rewrite(self, **kwargs) -> RewriteResult:
            return RewriteResult(
                rewritten="改写后的检索问题",
                sub_questions=["改写后的检索问题"],
                keywords=["关键词"],
                needs_rewrite=True,
            )

        monkeypatch.setattr(ChatQueryRewriteService, "rewrite", fake_rewrite)
        ctx = _ctx()
        result = await QueryRewriteStage().process(ctx)
        assert result.signal == StageSignal.CONTINUE
        assert ctx.rewritten_question == "改写后的检索问题"
        assert ctx.rewrite_sub_questions == ["改写后的检索问题"]

    async def test_continue_on_rewrite_fallback(self, monkeypatch):
        """需要改写但 LLM 失败回退（needs_rewrite=True，rewritten=原问题）→ CONTINUE。"""

        async def fake_rewrite(self, **kwargs) -> RewriteResult:
            return RewriteResult(
                rewritten="原问题",
                sub_questions=["原问题"],
                keywords=[],
                needs_rewrite=True,
            )

        monkeypatch.setattr(ChatQueryRewriteService, "rewrite", fake_rewrite)
        ctx = _ctx(question="原问题")
        result = await QueryRewriteStage().process(ctx)
        assert result.signal == StageSignal.CONTINUE
        assert ctx.rewritten_question == "原问题"
