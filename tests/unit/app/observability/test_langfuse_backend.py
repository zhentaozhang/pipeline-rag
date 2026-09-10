"""LangfuseTraceExporter 适配层测试（mock 外部 langfuse 客户端）"""

from app.observability.langfuse_backend import KIND_TO_AS_TYPE, LangfuseTraceExporter


class FakeObs:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.children: list[FakeObs] = []

    def start_observation(self, **kwargs):
        self.calls.append(("start_observation", kwargs))
        child = FakeObs()
        self.children.append(child)
        return child

    def end(self, **kwargs):
        self.calls.append(("end", kwargs))

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))

    def score(self, **kwargs):
        self.calls.append(("score", kwargs))


class FakeClient:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.obs = FakeObs()

    def start_observation(self, **kwargs):
        self.calls.append(("start_observation", kwargs))
        return self.obs

    def flush(self):
        self.calls.append(("flush", {}))


def _make_exporter():
    client = FakeClient()
    exporter = LangfuseTraceExporter(client, "trace-1", "conv-1", 42, "sess-1")
    return client, exporter


def test_kind_mapping():
    assert KIND_TO_AS_TYPE["llm"] == "generation"
    assert KIND_TO_AS_TYPE["agent"] == "agent"
    assert KIND_TO_AS_TYPE["tool"] == "tool"
    assert KIND_TO_AS_TYPE["evaluation"] == "evaluator"
    assert KIND_TO_AS_TYPE["retrieval"] == "retriever"
    assert KIND_TO_AS_TYPE["pipeline"] == "span"
    assert KIND_TO_AS_TYPE["channel"] == "span"


def test_start_root_maps_trace_context_and_metadata():
    client, exporter = _make_exporter()
    root = exporter.start_root("exchange", input="hello", kind="pipeline")

    assert root is client.obs
    args = client.calls[0][1]
    assert args["trace_context"] == {"trace_id": "trace-1"}
    assert args["name"] == "exchange"
    assert args["as_type"] == "span"
    assert args["input"] == "hello"
    assert args["metadata"]["conversation_id"] == "conv-1"
    assert args["metadata"]["exchange_id"] == 42
    assert args["metadata"]["session_id"] == "sess-1"


def test_start_span_nests_under_parent():
    client, exporter = _make_exporter()
    root = exporter.start_root("exchange", kind="pipeline")
    child = exporter.start_span(root, "memory_load", input="q", kind="pipeline")

    assert child is root.children[0]
    args = root.calls[0][1]
    assert args["name"] == "memory_load"
    assert args["as_type"] == "span"
    assert args["input"] == "q"


def test_end_span_calls_update_then_end():
    client, exporter = _make_exporter()
    root = exporter.start_root("exchange", kind="pipeline")
    exporter.end_span(root, output="answer", level="ERROR")

    assert root.calls[-1][0] == "end"
    assert root.calls[-2][0] == "update"
    assert root.calls[-2][1]["output"] == "answer"
    assert root.calls[-2][1]["level"] == "ERROR"


def test_add_score_maps_to_score():
    client, exporter = _make_exporter()
    root = exporter.start_root("exchange", kind="pipeline")
    exporter.add_score(root, "faithfulness", 0.9, reason="ok")

    assert root.calls[-1][0] == "score"
    assert root.calls[-1][1]["name"] == "faithfulness"
    assert root.calls[-1][1]["value"] == 0.9
    assert root.calls[-1][1]["comment"] == "ok"


def test_flush_calls_client_flush():
    client, exporter = _make_exporter()
    exporter.flush()

    assert client.calls[-1][0] == "flush"


def test_record_generation_maps_model_usage_cost():
    client, exporter = _make_exporter()
    root = exporter.start_root("exchange", kind="pipeline")
    exporter.record_generation(
        root,
        "rag_answer",
        model="deepseek-chat",
        input="question",
        output="answer",
        usage_details={"input": 10, "output": 5, "total": 15},
        cost_details={"input": 0.001, "output": 0.002, "total": 0.003},
    )

    # 父 observation 记录了一次 start_observation（as_type=generation + model）
    start_call = next(c for c in root.calls if c[0] == "start_observation")
    assert start_call[1]["as_type"] == "generation"
    assert start_call[1]["model"] == "deepseek-chat"
    assert start_call[1]["input"] == "question"

    # generation observation 自身记录 update(usage/cost/output) + end
    gen = root.children[0]
    update_call = next(c for c in gen.calls if c[0] == "update")
    assert update_call[1]["output"] == "answer"
    assert update_call[1]["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert update_call[1]["cost_details"] == {"input": 0.001, "output": 0.002, "total": 0.003}
    assert any(c[0] == "end" for c in gen.calls)
