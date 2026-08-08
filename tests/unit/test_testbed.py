"""冒烟测试：验证测试地基可用、fake_llm 真生效且不碰真实网络。"""

import pytest


async def test_fake_llm_usage_in_calls(fake_llm):
    fake_llm.queue_json({"rewrite": "重写后的查询", "should_split": False, "sub_questions": []})
    from app.orchestrator.query_rewriter import ChatQueryRewriteService

    svc = ChatQueryRewriteService()
    result = await svc.rewrite("太短", force=True)
    assert result.rewritten == "重写后的查询"
    assert fake_llm.calls, "fake_llm 应被调用"
    assert fake_llm.calls[0]["record"].get("model") is not None


async def test_fake_llm_infra_raises_when_empty(fake_llm):
    """fake client 空队列直接调用时必须失败，避免悄悄连到真实网络。"""

    with pytest.raises(AssertionError):
        await fake_llm._client.chat.completions.create(
            model="x", messages=[{"role": "user", "content": "hi"}]
        )


async def test_rewrite_falls_back_on_llm_error(fake_llm):
    """LLM 改写失败时 rewrite() 自动回退到规则拆分，而不是崩溃。"""
    from app.orchestrator.query_rewriter import ChatQueryRewriteService

    svc = ChatQueryRewriteService()
    result = await svc.rewrite("第一个问题；第二个问题", force=True)
    assert result.rewritten == "第一个问题；第二个问题"
    assert result.sub_questions == ["第一个问题", "第二个问题"]