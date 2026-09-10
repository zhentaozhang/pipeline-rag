"""rag_stream._record_generation 辅助函数测试"""

from app.executors.rag_stream import _record_generation


class FakeTracer:
    def __init__(self):
        self.calls: list[dict] = []

    def record_generation(self, name, **kwargs):
        self.calls.append({"name": name, **kwargs})


class FakeTask:
    def __init__(self, tracer=None):
        self.tracer = tracer


def test_record_generation_formats_usage_and_cost():
    task = FakeTask(tracer=FakeTracer())
    _record_generation(task, "rag_answer", "q", "a", prompt_tokens=10, completion_tokens=5)

    call = task.tracer.calls[0]
    assert call["name"] == "rag_answer"
    assert call["model"]
    assert call["input"] == "q"
    assert call["output"] == "a"
    assert call["usage"] == {"input": 10, "output": 5, "total": 15}
    assert call["cost"]["total"] > 0


def test_record_generation_noop_without_tracer():
    task = FakeTask(tracer=None)
    _record_generation(task, "rag_answer", "q", "a", prompt_tokens=10, completion_tokens=5)
    # 不抛异常即通过


def test_record_generation_noop_when_tracer_lacks_method():
    class NoRecordTracer:
        pass

    task = FakeTask(tracer=NoRecordTracer())
    _record_generation(task, "rag_answer", "q", "a", prompt_tokens=10, completion_tokens=5)
    # 不抛异常即通过
