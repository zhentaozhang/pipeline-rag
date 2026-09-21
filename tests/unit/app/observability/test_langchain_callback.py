"""TracerCallbackHandler 测试：LangGraph/LangChain LLM 调用 → 自研 Tracer generation"""

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.observability.langchain_callback import TracerCallbackHandler


class FakeTracer:
    def __init__(self):
        self.calls: list[dict] = []

    def record_generation(self, name, **kwargs):
        self.calls.append({"name": name, **kwargs})


@pytest.mark.asyncio
async def test_callback_records_generation_on_llm_end():
    tracer = FakeTracer()
    handler = TracerCallbackHandler(tracer, name_prefix="react_agent")
    run_id = uuid.uuid4()

    await handler.on_chat_model_start(
        {"kwargs": {"model_name": "deepseek-chat"}},
        [[HumanMessage(content="hi")]],
        run_id=run_id,
    )
    response = LLMResult(
        generations=[[ChatGeneration(message=AIMessage(content="hello"))]],
        llm_output={
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model_name": "deepseek-chat",
        },
    )
    await handler.on_llm_end(response, run_id=run_id)

    assert tracer.calls, "应记录 generation"
    call = tracer.calls[0]
    assert call["name"] == "react_agent_llm"
    assert call["model"] == "deepseek-chat"
    assert call["input"] == "hi"
    assert call["output"] == "hello"
    assert call["usage"] == {"input": 10, "output": 5, "total": 15}
    assert call["cost"]["total"] > 0


@pytest.mark.asyncio
async def test_callback_tolerates_missing_usage_and_unknown_run():
    tracer = FakeTracer()
    handler = TracerCallbackHandler(tracer)

    # on_llm_end without prior start：不抛异常
    response = LLMResult(generations=[[ChatGeneration(message=AIMessage(content="x"))]])
    await handler.on_llm_end(response, run_id=uuid.uuid4())

    assert tracer.calls[0]["usage"] == {"input": 0, "output": 0, "total": 0}
