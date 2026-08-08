import pytest

from app.common.pipeline import (
    Pipeline,
    PipelineError,
    PipelineStage,
    Stage,
    StageResult,
    StageSignal,
)


class DummyStage(Stage):
    def __init__(self, name, result=None, raises=None):
        self.name = name
        self._result = result if result is not None else StageResult()
        self._raises = raises
        self.calls = 0

    async def process(self, ctx):
        self.calls += 1
        if self._raises:
            raise self._raises
        return self._result


class TestPipeline:
    async def test_simple_continue_chain(self):
        s1 = DummyStage("s1", StageResult(context="ctx1"))
        s2 = DummyStage("s2", StageResult(context="ctx2"))
        pipeline = Pipeline(
            [
                PipelineStage(s1),
                PipelineStage(s2),
            ]
        )
        with pytest.raises(PipelineError):
            await pipeline.run("start")

    async def test_terminate_returns_plan(self):
        s1 = DummyStage("s1", StageResult(signal=StageSignal.TERMINATE, plan="final"))
        s2 = DummyStage("s2")
        pipeline = Pipeline([PipelineStage(s1), PipelineStage(s2)])
        assert await pipeline.run("ctx") == "final"
        assert s2.calls == 0

    async def test_skip_keeps_context(self):
        s1 = DummyStage("s1", StageResult(context="new_ctx"))
        s2 = DummyStage("s2", StageResult(signal=StageSignal.SKIP))
        s3 = DummyStage("s3", StageResult(context="s3_ctx"))
        pipeline = Pipeline([PipelineStage(s1), PipelineStage(s2), PipelineStage(s3)])
        with pytest.raises(PipelineError):
            await pipeline.run("start")

    async def test_skip_then_terminate(self):
        s1 = DummyStage("s1", StageResult(signal=StageSignal.SKIP))
        s2 = DummyStage("s2", StageResult(signal=StageSignal.TERMINATE, plan="done"))
        pipeline = Pipeline([PipelineStage(s1), PipelineStage(s2)])
        assert await pipeline.run("ctx") == "done"

    async def test_context_flows_through_chain(self):
        seen = []

        class CaptureStage(Stage):
            def __init__(self, name, emit):
                self.name = name
                self._emit = emit

            async def process(self, ctx):
                seen.append((self.name, ctx))
                return StageResult(context=self._emit)

        pipeline = Pipeline(
            [
                PipelineStage(CaptureStage("a", "A")),
                PipelineStage(CaptureStage("b", "B")),
                PipelineStage(CaptureStage("c", None)).when(lambda ctx: ctx == "B"),
            ]
        )
        with pytest.raises(PipelineError):
            await pipeline.run("init")
        assert seen == [("a", "init"), ("b", "A"), ("c", "B")]

    async def test_condition_false_skips_stage(self):
        s1 = DummyStage("s1", StageResult(context="ctx1"))
        s2 = DummyStage("s2", StageResult(context="ctx2"))
        pipeline = Pipeline(
            [
                PipelineStage(s1),
                PipelineStage(s2).when(lambda ctx: False),
            ]
        )
        with pytest.raises(PipelineError):
            await pipeline.run("start")
        assert s2.calls == 0

    async def test_terminate_without_plan_raises(self):
        s1 = DummyStage("s1", StageResult(signal=StageSignal.TERMINATE, plan=None))
        pipeline = Pipeline([PipelineStage(s1)])
        with pytest.raises(PipelineError, match="TERMINATE"):
            await pipeline.run("ctx")

    async def test_no_stages_raises(self):
        pipeline = Pipeline()
        with pytest.raises(PipelineError):
            await pipeline.run("ctx")

    async def test_add_stage_chains(self):
        s1 = DummyStage("s1", StageResult(signal=StageSignal.TERMINATE, plan="done"))
        pipeline = Pipeline().add_stage(PipelineStage(s1))
        assert await pipeline.run("ctx") == "done"

    async def test_when_fluent(self):
        s1 = DummyStage("s1", StageResult(context="x"))
        stage_wrapper = PipelineStage(s1)
        assert stage_wrapper.when(lambda ctx: True) is stage_wrapper
        assert stage_wrapper.condition is not None

    async def test_all_continue_raises(self):
        s1 = DummyStage("s1", StageResult(context="c1"))
        pipeline = Pipeline([PipelineStage(s1)])
        with pytest.raises(PipelineError, match="未产生结果"):
            await pipeline.run("start")


class TestStageResult:
    def test_defaults(self):
        r = StageResult()
        assert r.signal == StageSignal.CONTINUE
        assert r.context is None
        assert r.plan is None

    def test_signal_is_str_enum(self):
        assert StageSignal.CONTINUE.value == "continue"
        assert StageSignal.TERMINATE.value == "terminate"
        assert StageSignal.SKIP.value == "skip"


class TestPipelineStage:
    def test_when_sets_condition(self):
        s = DummyStage("s", StageResult())
        wrapper = PipelineStage(s)

        def cond(ctx):
            return True
        assert wrapper.when(cond) is wrapper
        assert wrapper.condition is cond
