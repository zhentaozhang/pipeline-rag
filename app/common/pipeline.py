"""
Pipeline 模式基础设施 — 通用的管道编排抽象。

提供 Pipeline[C, R] 泛型管道，支持：
- 顺序执行 Stage（每个 Stage 接收上下文 C，返回 StageResult）
- 短路信号 TERMINATE（立即返回最终结果 R）
- 跳过信号 SKIP（跳过当前 Stage）
- 条件执行 .when()（满足条件才执行）
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Generic, TypeVar

C = TypeVar("C")
R = TypeVar("R")


class StageSignal(StrEnum):
    """Stage 返回信号：控制管道执行流程"""

    CONTINUE = auto()  # 继续到下一 Stage
    TERMINATE = auto()  # 终止管道，立即返回 plan
    SKIP = auto()  # 跳过当前 Stage 的剩余处理


@dataclass
class StageResult(Generic[C, R]):
    """Stage 的执行结果"""

    signal: StageSignal = StageSignal.CONTINUE
    context: C | None = None  # CONTINUE 时携带更新后的上下文
    plan: R | None = None  # TERMINATE 时携带最终结果


class Stage(ABC, Generic[C, R]):
    """管道中单个处理阶段的抽象基类"""

    name: str = ""

    @abstractmethod
    async def process(self, ctx: C) -> StageResult[C, R]: ...


@dataclass
class PipelineStage(Generic[C, R]):
    """管道阶段的包装器，支持条件执行"""

    handler: Stage[C, R]
    condition: Callable[[C], bool] | None = None

    def when(self, cond: Callable[[C], bool]) -> "PipelineStage[C, R]":
        self.condition = cond
        return self


class PipelineError(Exception):
    """管道执行异常"""


class Pipeline(Generic[C, R]):
    """
    可组合管道。

    按顺序执行 PipelineStage 列表，每个 stage 返回 StageResult：
    - CONTINUE: 更新上下文，继续下一 stage
    - TERMINATE: 立即返回 plan，跳过后续 stage
    - SKIP: 不更新上下文，继续下一 stage

    支持条件执行：通过 .when() 设置条件，条件不满足时跳过该 stage。
    """

    def __init__(self, stages: list[PipelineStage[C, R]] | None = None) -> None:
        self.stages = stages or []

    async def run(self, ctx: C) -> R:
        import time as _time

        import structlog as _slog

        _logger = _slog.get_logger(__name__)
        for stage_wrapper in self.stages:
            # 条件检查：不满足则跳过
            if stage_wrapper.condition is not None and not stage_wrapper.condition(ctx):
                continue

            _t0 = _time.monotonic()
            result = await stage_wrapper.handler.process(ctx)
            _elapsed_ms = (_time.monotonic() - _t0) * 1000
            if _elapsed_ms >= 50:  # 只记录 >50ms 的 stage（定位延迟黑洞，P0）
                _logger.info(
                    "stage timing",
                    stage=getattr(stage_wrapper, "name", None)
                    or getattr(stage_wrapper.handler, "name", None)
                    or type(stage_wrapper.handler).__name__,
                    elapsed_ms=round(_elapsed_ms, 1),
                )

            if result.signal == StageSignal.TERMINATE:
                if result.plan is not None:
                    return result.plan
                raise PipelineError(
                    f"Stage '{stage_wrapper.handler.name}' 返回 TERMINATE 信号但未提供 plan"
                )

            if result.signal == StageSignal.CONTINUE and result.context is not None:
                ctx = result.context

            # SKIP: 不做任何操作，继续下一 stage

        raise PipelineError("管道执行完毕但未产生结果：所有 Stage 均返回 CONTINUE")

    def add_stage(self, stage: PipelineStage[C, R]) -> "Pipeline[C, R]":
        self.stages.append(stage)
        return self
