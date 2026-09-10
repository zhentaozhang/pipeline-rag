"""Tracer 与 LangfuseTraceExporter 的接线测试（mock 外部 langfuse 客户端）"""

from app.observability import langfuse_client as lfc
from app.observability.enums import SpanKind
from app.observability.models import Trace
from app.observability.tracer import Tracer


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


def _make_tracer(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(lfc, "get_langfuse", lambda: client)
    tracer = Tracer(
        db=None, trace_id="t1", conversation_id="c1", exchange_id=1, sample_rate=1.0
    )
    tracer._trace = Trace(
        trace_id="t1", conversation_id="c1", exchange_id=1, session_id="s1"
    )
    return client, tracer


def test_tracer_reports_root_span(monkeypatch):
    client, tracer = _make_tracer(monkeypatch)
    tracer.root("exchange", kind=SpanKind.PIPELINE, input="hello")

    assert client.calls[0][0] == "start_observation"
    args = client.calls[0][1]
    assert args["trace_context"] == {"trace_id": "t1"}
    assert args["name"] == "exchange"
    assert args["as_type"] == "span"
    assert args["metadata"]["conversation_id"] == "c1"
    assert args["metadata"]["exchange_id"] == 1
    assert args["metadata"]["session_id"] == "s1"


def test_tracer_reports_score_on_root(monkeypatch):
    client, tracer = _make_tracer(monkeypatch)
    tracer.root("exchange", kind=SpanKind.PIPELINE)
    tracer.attach_score("faithfulness", 0.9, reason="ok")

    assert any(c[0] == "score" for c in client.obs.calls)
    score_call = next(c for c in client.obs.calls if c[0] == "score")
    assert score_call[1]["name"] == "faithfulness"
    assert score_call[1]["value"] == 0.9


async def test_tracer_reports_child_span_lifecycle(monkeypatch):
    client, tracer = _make_tracer(monkeypatch)
    tracer.root("exchange", kind=SpanKind.PIPELINE)

    async with tracer.span("memory_load", kind=SpanKind.PIPELINE) as _span:
        pass

    root_obs = client.obs
    assert root_obs.children, "root 应有子 span"
    child = root_obs.children[0]
    assert any(c[0] == "end" for c in child.calls)


def test_tracer_record_generation_nests_under_root(monkeypatch):
    client, tracer = _make_tracer(monkeypatch)
    tracer.root("exchange", kind=SpanKind.PIPELINE)

    tracer.record_generation(
        "rag_answer",
        model="deepseek-chat",
        input="q",
        output="a",
        usage={"input": 10, "output": 5, "total": 15},
        cost={"input": 0.001, "output": 0.002, "total": 0.003},
    )

    root_obs = client.obs
    assert root_obs.children, "root 下应有 generation"
    gen = root_obs.children[0]
    assert any(c[0] == "end" for c in gen.calls)
    update = next(c for c in gen.calls if c[0] == "update")
    assert update[1]["usage_details"]["total"] == 15
    assert update[1]["cost_details"]["total"] == 0.003
