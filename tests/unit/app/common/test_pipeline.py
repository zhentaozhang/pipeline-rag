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

    def test_stage_name_defaults_to_class_name(self):
        class NamedStage(Stage):
            async def process(self, ctx):
                return StageResult(signal=StageSignal.TERMINATE, plan="done")

        assert NamedStage.name == "NamedStage"
        assert PipelineStage(NamedStage()).name == "NamedStage"

    async def test_fast_stage_is_observed_in_histogram(self, monkeypatch):
        """所有阶段都进 Histogram；50ms 门槛只用于慢阶段日志，不用于埋点。"""
        import app.common.pipeline as pipeline_module
        import app.observability.tracer as tracer_module

        class FakeHistogram:
            def __init__(self):
                self.label_values = []
                self.observations = []

            def labels(self, **kwargs):
                self.label_values.append(kwargs)
                return self

            def observe(self, value):
                self.observations.append(value)

        histogram = FakeHistogram()
        monkeypatch.setattr(tracer_module, "STAGE_DURATION_SECONDS", histogram)
        # 通过固定时钟保证耗时为 1ms（远小于原来的 50ms 采样门槛）。
        clock_calls = 0

        def clock():
            nonlocal clock_calls
            clock_calls += 1
            return 1.0 if clock_calls == 1 else 1.001

        monkeypatch.setattr(pipeline_module.time, "monotonic", clock)

        stage = DummyStage("fast-stage", StageResult(signal=StageSignal.TERMINATE, plan="done"))
        result = await Pipeline([PipelineStage(stage)]).run("ctx")

        assert result == "done"
        assert histogram.label_values == [{"kind": "stage", "name": "fast-stage", "status": "ok"}]
        assert histogram.observations == pytest.approx([0.001])

    async def test_failed_stage_is_observed_with_error_status(self, monkeypatch):
        import app.common.pipeline as pipeline_module
        import app.observability.tracer as tracer_module

        class FakeHistogram:
            def __init__(self):
                self.label_values = []
                self.observations = []

            def labels(self, **kwargs):
                self.label_values.append(kwargs)
                return self

            def observe(self, value):
                self.observations.append(value)

        histogram = FakeHistogram()
        monkeypatch.setattr(tracer_module, "STAGE_DURATION_SECONDS", histogram)
        clock_calls = 0

        def clock():
            nonlocal clock_calls
            clock_calls += 1
            return 2.0 if clock_calls == 1 else 2.001

        monkeypatch.setattr(pipeline_module.time, "monotonic", clock)
        stage = DummyStage("failed-stage", raises=ValueError("stage failed"))

        with pytest.raises(ValueError, match="stage failed"):
            await Pipeline([PipelineStage(stage)]).run("ctx")

        assert histogram.label_values == [
            {"kind": "stage", "name": "failed-stage", "status": "error"}
        ]
        assert histogram.observations == pytest.approx([0.001])


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
