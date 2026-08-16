"""SSE 流式对话并发压测（量化能力 #4）

对真实服务（/api/chat/stream）发起 N 并发流式请求，统计：
- 成功率 / 失败原因分布
- 端到端延迟 P50 / P90 / P99
- 首 token 延迟 P50 / P90 / P99
- 全部流是否完整收到 done 事件

用法：
    python -m scripts.bench.sse_bench --base http://localhost:8080 --concurrency 20 --requests 40

注意：真实 LLM 调用会产生 token 成本，建议先用少量请求验证链路；
压测 QPS/并发上限前可用 --mock 让服务端走缓存/无证据兜底路径降本。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from typing import Any

import httpx


def _percentile(values: list[float], q: float) -> float:
    """线性插值分位（p50 = 标准中位数）"""
    if not values:
        return 0.0
    values = sorted(values)
    pos = q * (len(values) - 1)
    lo = int(pos)
    hi = min(len(values) - 1, lo + 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


async def _one_stream(
    client: httpx.AsyncClient,
    base: str,
    question: str,
    conv_prefix: str,
    idx: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    first_token_at: float | None = None
    got_done = False
    error: str | None = None
    try:
        async with client.stream(
            "POST",
            f"{base}/api/chat/stream",
            json={
                "question": question,
                "conversationId": f"{conv_prefix}-{idx}",
                "chatMode": "auto",
            },
            timeout=httpx.Timeout(120.0, connect=10.0),
        ) as resp:
            if resp.status_code != 200:
                return {"ok": False, "error": f"http {resp.status_code}"}
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    evt = json.loads(payload)
                except ValueError:
                    continue
                if first_token_at is None and evt.get("type") in ("text", "thinking"):
                    first_token_at = time.perf_counter()
                if evt.get("type") == "done":
                    got_done = True
    except Exception as e:  # noqa: BLE001
        error = f"{type(e).__name__}: {str(e)[:80]}"

    elapsed = time.perf_counter() - started
    return {
        "ok": got_done and error is None,
        "error": error or ("" if got_done else "no done event"),
        "elapsed_ms": elapsed * 1000,
        "first_token_ms": ((first_token_at - started) * 1000) if first_token_at else None,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="SSE 流式对话并发压测")
    parser.add_argument("--base", default="http://localhost:8080", help="服务地址")
    parser.add_argument("--concurrency", type=int, default=10, help="并发数")
    parser.add_argument("--requests", type=int, default=20, help="总请求数")
    parser.add_argument("--question", default="什么是 RAG？请简要说明。", help="压测问题")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(args.concurrency)

    async def _worker(i: int) -> None:
        async with sem, httpx.AsyncClient() as client:
            results.append(
                await _one_stream(client, args.base, args.question, "bench", i)
            )

    started = time.perf_counter()
    await asyncio.gather(*[_worker(i) for i in range(args.requests)])
    wall = time.perf_counter() - started

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    elapsed = [r["elapsed_ms"] for r in ok]
    first = [r["first_token_ms"] for r in ok if r["first_token_ms"] is not None]

    print("=" * 56)
    print(f"总请求 {args.requests} | 并发 {args.concurrency} | 耗时 {wall:.1f}s")
    print(f"成功 {len(ok)} | 失败 {len(failed)}")
    if failed:
        from collections import Counter

        for reason, cnt in Counter(r["error"] for r in failed).most_common(5):
            print(f"  失败原因 [{cnt}] {reason}")
    if ok:
        print(f"QPS(成功) {len(ok) / wall:.1f}")
        print(f"端到端延迟 ms: P50={_percentile(elapsed, 0.5):.0f} P90={_percentile(elapsed, 0.9):.0f} P99={_percentile(elapsed, 0.99):.0f} mean={statistics.mean(elapsed):.0f}")
        if first:
            print(f"首token ms:  P50={_percentile(first, 0.5):.0f} P90={_percentile(first, 0.9):.0f} P99={_percentile(first, 0.99):.0f}")
    print("=" * 56)
    return 1 if failed and len(failed) > len(ok) * 0.5 else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
