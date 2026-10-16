"""
Pipeline 模式基础设施 — 通用的管道编排抽象。

提供 Pipeline[C, R] 泛型管道，支持：
- 顺序执行 Stage（每个 Stage 接收上下文 C，返回 StageResult）
- 短路信号 TERMINATE（立即返回最终结果 R）
- 跳过信号 SKIP（跳过当前 Stage）
- 条件执行 .when()（满足条件才执行）
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Any, Generic, TypeVar

import structlog

logger = structlog.get_logger(__name__)

C = TypeVar("C")
R = TypeVar("R")

# 单阶段耗时超过该阈值时额外记一条结构化日志（用于定位延迟黑洞）。
# 注意：指标埋点不受该阈值限制，见 Pipeline.run。
_SLOW_STAGE_THRESHOLD_MS = 50


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
    """管道中单个处理阶段的抽象基类。

    ``name`` 供日志与指标使用：子类未显式声明时自动取类名，
    因此 Pipeline 不再需要用 getattr 链去猜测阶段名。
    """

    name: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 显式声明优先；未声明则用类名兜底（测试桩常在 __init__ 里覆盖实例属性）
        if not cls.__dict__.get("name"):
            cls.name = cls.__name__

    @abstractmethod
    async def process(self, ctx: C) -> StageResult[C, R]: ...


@dataclass
class PipelineStage(Generic[C, R]):
    """管道阶段的包装器，支持条件执行"""

    handler: Stage[C, R]
    condition: Callable[[C], bool] | None = None

    @property
    def name(self) -> str:
        """阶段名（来自 handler），供日志与指标统一取用。"""
        return self.handler.name

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
        for stage_wrapper in self.stages:
            # 条件检查：不满足则跳过
            if stage_wrapper.condition is not None and not stage_wrapper.condition(ctx):
                continue

            stage_name = stage_wrapper.name

            _t0 = time.monotonic()
            try:
                result = await stage_wrapper.handler.process(ctx)
            except Exception:
                _elapsed_ms = (time.monotonic() - _t0) * 1000
                self._record_stage_duration(stage_name, _elapsed_ms, status="error")
                self._log_slow_stage(stage_name, _elapsed_ms, status="error")
                raise

            _elapsed_ms = (time.monotonic() - _t0) * 1000
            self._record_stage_duration(stage_name, _elapsed_ms, status="ok")
            self._log_slow_stage(stage_name, _elapsed_ms, status="ok")

            if result.signal == StageSignal.TERMINATE:
                if result.plan is not None:
                    return result.plan
                raise PipelineError(f"Stage '{stage_name}' 返回 TERMINATE 信号但未提供 plan")

            if result.signal == StageSignal.CONTINUE and result.context is not None:
                ctx = result.context

            # SKIP: 不做任何操作，继续下一 stage

        raise PipelineError("管道执行完毕但未产生结果：所有 Stage 均返回 CONTINUE")

    @staticmethod
    def _record_stage_duration(stage_name: str, elapsed_ms: float, status: str) -> None:
        """记录所有执行阶段（包含快速成功与失败阶段）的完整时延样本。"""
        try:
            from app.observability.tracer import STAGE_DURATION_SECONDS

            STAGE_DURATION_SECONDS.labels(kind="stage", name=stage_name, status=status).observe(
                elapsed_ms / 1000.0
            )
        except Exception:
            # 指标系统故障不得阻断业务管道。
            pass

    @staticmethod
    def _log_slow_stage(stage_name: str, elapsed_ms: float, status: str) -> None:
        if elapsed_ms >= _SLOW_STAGE_THRESHOLD_MS:
            logger.info(
                "stage timing",
                stage=stage_name,
                elapsed_ms=round(elapsed_ms, 1),
                status=status,
            )

    def add_stage(self, stage: PipelineStage[C, R]) -> "Pipeline[C, R]":
        self.stages.append(stage)
        return self
