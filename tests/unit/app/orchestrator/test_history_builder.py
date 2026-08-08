import types

from app.chat.schema import HistoryPlanningContext
from app.orchestrator.history_builder import HistoryBuilder


class FakeSummaryPayload:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeMemory:
    def __init__(self, summary_payload=None, recent_transcript="", **attrs):
        self.summary_payload = summary_payload
        self.recent_transcript = recent_transcript
        for k, v in attrs.items():
            setattr(self, k, v)


class TestBuildPlanningContext:
    def test_no_payload_empty(self):
        ctx = HistoryBuilder.build_planning_context(FakeMemory(summary_payload=None))
        assert ctx.goals == []
        assert ctx.facts == []

    def test_payload_mapping(self):
        payload = FakeSummaryPayload(
            conversation_goal="配置数据库",
            stable_facts=["事实1", ""],
            pending_questions=["问题1"],
            retrieval_hints=["提示1"],
        )
        ctx = HistoryBuilder.build_planning_context(FakeMemory(summary_payload=payload))
        assert ctx.goals == ["配置数据库"]
        assert ctx.facts == ["事实1", ""]
        assert ctx.pending_questions == ["问题1"]
        assert ctx.retrieval_hints == ["提示1"]


class TestBuildStructuredPlanningHistory:
    def test_empty_ctx(self):
        assert HistoryBuilder._build_structured_planning_history(None) == ""

    def test_full(self):
        ctx = HistoryPlanningContext(
            goals=["目标A"],
            facts=["事实1", "事实2", " ", "事实3", "事实4", "事实5", "事实6"],
            pending_questions=["问题1"],
            retrieval_hints=["提示1"],
        )
        out = HistoryBuilder._build_structured_planning_history(ctx)
        assert "【会话目标】\n目标A" in out
        assert "【已确认事实】" in out
        assert out.count("- 事实") == 5
        assert "【待跟进问题】" in out
        assert "【检索提示】" in out

    def test_goals_only(self):
        out = HistoryBuilder._build_structured_planning_history(HistoryPlanningContext(goals=["g"]))
        assert out == "【会话目标】\ng"


class TestBuildPlanningHistory:
    def test_no_recent_uses_structured(self, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.history_builder.get_settings",
            lambda: types.SimpleNamespace(rag=types.SimpleNamespace(planning_history_max_chars=1000)),
        )
        ctx = HistoryPlanningContext(goals=["目标A"])
        out = HistoryBuilder.build_planning_history(FakeMemory(recent_transcript=""), ctx)
        assert "目标A" in out

    def test_recent_budget_split(self, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.history_builder.get_settings",
            lambda: types.SimpleNamespace(rag=types.SimpleNamespace(planning_history_max_chars=100)),
        )
        ctx = HistoryPlanningContext(goals=["很长的目标" * 20])
        recent = "recent" * 30
        out = HistoryBuilder.build_planning_history(FakeMemory(recent_transcript=recent), ctx)
        assert len(out) <= 100

    def test_zero_budget_still_works(self, monkeypatch):
        monkeypatch.setattr(
            "app.orchestrator.history_builder.get_settings",
            lambda: types.SimpleNamespace(rag=types.SimpleNamespace(planning_history_max_chars=0)),
        )
        out = HistoryBuilder.build_planning_history(FakeMemory(recent_transcript="x"), HistoryPlanningContext(goals=["g"]))
        assert isinstance(out, str)


class TestBuildAnswerContext:
    def test_delegates_to_rewriter(self, monkeypatch):
        class FakeAssembler:
            def _assemble_answer_history(self, question, transcript):
                return types.SimpleNamespace(
                    rendered_text="ah", recent_context="rc", follow_up_question=True
                )

        monkeypatch.setattr(
            "app.orchestrator.history_builder.ChatQueryRewriteService", FakeAssembler
        )
        ctx = HistoryBuilder.build_answer_context("q", "t")
        assert ctx.rendered_text == "ah"
        assert ctx.recent_context == "rc"
        assert ctx.follow_up_question is True
