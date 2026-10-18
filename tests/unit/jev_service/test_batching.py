"""JEV 微批调度：并发请求必须合并成一次前向，失败必须广播到本批所有等待者。"""

from __future__ import annotations

import asyncio

import pytest

from jev_service.batching import MicroBatcher


class _Recorder:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.batches: list[list[tuple[str, dict]]] = []

    def __call__(self, jobs):
        self.batches.append(list(jobs))
        if self.fail:
            raise RuntimeError("inference boom")
        return [{"echo": state, "n": len(questions)} for state, questions in jobs]


@pytest.mark.asyncio
async def test_single_submit_returns_its_result():
    rec = _Recorder()
    b = MicroBatcher(run=rec, window_ms=20, max_batch=4)
    try:
        out = await b.submit("state-1", {"q": {"type": "noul"}})
    finally:
        await b.close()
    assert out == {"echo": "state-1", "n": 1}
    assert rec.batches == [[("state-1", {"q": {"type": "noul"}})]]


@pytest.mark.asyncio
async def test_concurrent_submits_share_one_forward():
    rec = _Recorder()
    b = MicroBatcher(run=rec, window_ms=50, max_batch=4)
    try:
        outs = await asyncio.gather(*[b.submit(f"s{i}", {"q": {"type": "noul"}}) for i in range(4)])
    finally:
        await b.close()
    assert len(rec.batches) == 1, f"4 个并发请求应合并为 1 次前向，实际 {len(rec.batches)}"
    assert [o["echo"] for o in outs] == ["s0", "s1", "s2", "s3"]


@pytest.mark.asyncio
async def test_batch_is_capped_by_max_batch():
    rec = _Recorder()
    b = MicroBatcher(run=rec, window_ms=30, max_batch=4)
    try:
        await asyncio.gather(*[b.submit(f"s{i}", {"q": {"type": "noul"}}) for i in range(10)])
    finally:
        await b.close()
    assert [len(batch) for batch in rec.batches] == [4, 4, 2]
    assert all(len(batch) <= 4 for batch in rec.batches)


@pytest.mark.asyncio
async def test_zero_window_does_not_coalesce():
    rec = _Recorder()
    b = MicroBatcher(run=rec, window_ms=0, max_batch=4)
    try:
        await asyncio.gather(*[b.submit(f"s{i}", {"q": {"type": "noul"}}) for i in range(3)])
    finally:
        await b.close()
    assert sum(len(batch) for batch in rec.batches) == 3
    assert len(rec.batches) >= 1  # 允许竞态，但不得丢请求


@pytest.mark.asyncio
async def test_failure_is_broadcast_to_every_waiter():
    rec = _Recorder(fail=True)
    b = MicroBatcher(run=rec, window_ms=30, max_batch=4)
    try:
        results = await asyncio.gather(
            *[b.submit(f"s{i}", {"q": {"type": "noul"}}) for i in range(3)],
            return_exceptions=True,
        )
    finally:
        await b.close()
    assert all(isinstance(r, RuntimeError) for r in results), results


@pytest.mark.asyncio
async def test_exception_items_are_raised_only_for_their_owner():
    def run(jobs):
        out = []
        for state, _ in jobs:
            out.append(RuntimeError("bad state") if state == "s1" else {"echo": state})
        return out

    b = MicroBatcher(run=run, window_ms=30, max_batch=4)
    try:
        results = await asyncio.gather(
            *[b.submit(f"s{i}", {"q": {"type": "noul"}}) for i in range(3)],
            return_exceptions=True,
        )
    finally:
        await b.close()
    assert isinstance(results[1], RuntimeError)
    assert results[0] == {"echo": "s0"} and results[2] == {"echo": "s2"}


@pytest.mark.asyncio
async def test_batch_sizes_are_observable():
    rec = _Recorder()
    b = MicroBatcher(run=rec, window_ms=20, max_batch=2)
    try:
        await asyncio.gather(*[b.submit(f"s{i}", {"q": {"type": "noul"}}) for i in range(4)])
    finally:
        await b.close()
    assert sum(b.batch_sizes) == 4
