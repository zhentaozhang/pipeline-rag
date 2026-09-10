"""AnswerQualityChecker 记录 Langfuse generation 测试"""

import pytest

from app.executors.rag import AnswerQualityChecker


class FakeTracer:
    def __init__(self):
        self.calls: list[dict] = []

    def record_generation(self, name, **kwargs):
        self.calls.append({"name": name, **kwargs})


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5


class _Message:
    content = '{"score": 9, "issues": [], "suggestion": "", "dimensions": {}}'


class _Choice:
    message = _Message()


class _Resp:
    usage = _Usage()
    choices = [_Choice()]


class _Completions:
    def __init__(self):
        self.last_kwargs: dict = {}

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _Resp()


class _Chat:
    completions = _Completions()


class _FakeOpenAI:
    chat = _Chat()


@pytest.mark.asyncio
async def test_quality_checker_records_generation(monkeypatch):
    tracer = FakeTracer()
    checker = AnswerQualityChecker(tracer=tracer)
    checker._openai = _FakeOpenAI()

    result = await checker._call_llm("prompt text")

    assert result["score"] == 9
    assert tracer.calls, "应记录 generation"
    call = tracer.calls[0]
    assert call["name"] == "quality_check"
    assert call["input"] == "prompt text"
    assert call["usage"] == {"input": 10, "output": 5, "total": 15}
    assert call["cost"]["total"] > 0
