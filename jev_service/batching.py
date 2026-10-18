"""JEV 微批调度器（与模型无关，便于单测）。

背景（2026-10-21 审计）：旧实现用全局 ``asyncio.Lock`` 把所有请求串行化，并发 6 时
p50 8.0s / p95 9.8s，41% 的决策直接撞 10s 超时。串行的根因不是"必须串行"，而是
"没有把并发请求合并成一次前向"。本模块只负责**收集与分配**，真正的推理由注入的
``run`` 回调完成（生产实现见 ``judger.judge_entries_multi``）。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

Job = tuple[str, dict[str, Any]]


class MicroBatcher:
    """在 ``window_ms`` 时间窗内把并发请求合并成一次批量推理。

    - ``max_batch``：单次合并的最大请求数（每请求内部还会再按问题数分批）；
    - ``window_ms <= 0``：退化为"不合并"，等价于旧行为。
    """

    def __init__(
        self,
        *,
        run: Callable[[list[Job]], list[dict[str, Any]]],
        window_ms: float = 20.0,
        max_batch: int = 4,
    ) -> None:
        self._run = run
        self._window = max(0.0, float(window_ms)) / 1000.0
        self._max_batch = max(1, int(max_batch))
        self._queue: asyncio.Queue[tuple[Job, asyncio.Future]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self.batch_sizes: list[int] = []  # 观测用

    async def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._loop())

    async def close(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._worker
            self._worker = None

    async def submit(self, state: str, questions: dict[str, Any]) -> dict[str, Any]:
        await self.start()  # 幂等：允许调用方忘记显式 start
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        await self._queue.put(((state, questions), fut))
        return await fut

    async def _loop(self) -> None:
        while True:
            (job, fut) = await self._queue.get()
            batch: list[tuple[Job, asyncio.Future]] = [(job, fut)]
            deadline = time.perf_counter() + self._window
            while len(batch) < self._max_batch:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                try:
                    nxt = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                except TimeoutError:
                    break
                batch.append(nxt)
            await self._dispatch(batch)

    async def _dispatch(self, batch: list[tuple[Job, asyncio.Future]]) -> None:
        self.batch_sizes.append(len(batch))
        try:
            results = await asyncio.to_thread(self._run, [job for job, _ in batch])
        except Exception as exc:  # noqa: BLE001 - 单批失败必须广播给本批所有等待者
            for _, fut in batch:
                if not fut.done():
                    fut.set_exception(exc)
            return
        for (_, fut), result in zip(batch, results, strict=False):
            if not fut.done():
                if isinstance(result, BaseException):
                    fut.set_exception(result)
                else:
                    fut.set_result(result)
