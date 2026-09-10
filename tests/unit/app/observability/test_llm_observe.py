"""llm_observe.record_generation 共享记录入口测试"""

from app.observability.llm_observe import record_generation


class FakeTracer:
    def __init__(self):
        self.calls: list[dict] = []

    def record_generation(self, name, **kwargs):
        self.calls.append({"name": name, **kwargs})


def test_record_generation_noop_when_tracer_none():
    record_generation(None, "x", model="m")  # 不抛异常


def test_record_generation_formats_usage_and_cost():
    tracer = FakeTracer()
    record_generation(
        tracer,
        "rag_answer",
        model="deepseek-chat",
        input="q",
        output="a",
        prompt_tokens=10,
        completion_tokens=5,
    )

    call = tracer.calls[0]
    assert call["name"] == "rag_answer"
    assert call["model"] == "deepseek-chat"
    assert call["input"] == "q"
    assert call["output"] == "a"
    assert call["usage"] == {"input": 10, "output": 5, "total": 15}
    assert call["cost"]["total"] > 0


def test_record_generation_noop_when_tracer_lacks_method():
    class NoRecord:
        pass

    record_generation(NoRecord(), "x", model="m")  # 不抛异常
