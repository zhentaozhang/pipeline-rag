"""JEV 决策延迟基准（Phase 0）

测量客户端观测到的端到端耗时（含 HTTP/序列化），覆盖：
- 单个 Noul / Choice / Score 原语
- 同一请求内的 N 个问题（验证批量前向的收益：N 个问题应接近 1 次前向耗时）

用法：
    python -m scripts.bench.jev_bench                 # 默认 1/2/4/8/16
    python -m scripts.bench.jev_bench --sizes 1,4,8 --repeats 10
    python -m scripts.bench.jev_bench --json /tmp/jev_bench.json

前提：jev-service 可达（JEV_BASE_URL）。不可达时快速失败。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

import structlog

logger = structlog.get_logger(__name__)


def _choice_question(i: int) -> dict:
    return {
        "type": "choice",
        "instructions": f"风险{i}是否存在？",
        "options": {"no": "否，不涉及", "yes": "是，存在该风险"},
    }


async def _timed(coro_factory) -> float:
    t0 = time.perf_counter()
    await coro_factory()
    return (time.perf_counter() - t0) * 1000


async def _measure(jev, questions: dict, repeats: int) -> list[float]:
    samples: list[float] = []
    for _ in range(repeats):
        samples.append(
            await _timed(lambda: jev.system_one(state="试用期一般多长时间？", questions=questions))
        )
    return samples


def _pct(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


async def run(sizes: list[int], repeats: int) -> dict:
    import httpx

    from app.infra.jev_client import get_jev_client

    jev = get_jev_client()
    device = "?"
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            device = (await c.get(f"{jev.base_url}/health")).json().get("device", "?")
    except Exception:
        logger.error("jev-service unreachable", base_url=jev.base_url)
        sys.exit(2)

    logger.info("jev bench start", base_url=jev.base_url, device=device, repeats=repeats)
    await jev.system_one(state="warmup", questions={"w": {"type": "noul", "instructions": "x"}})

    report: dict[str, dict[str, float]] = {}
    primitives = {
        "noul": {"type": "noul", "instructions": "该提问是否安全合规？"},
        "choice": _choice_question(0),
        "score": {
            "type": "score",
            "instructions": "答案质量打分",
            "levels": ["差", "中", "好"],
        },
    }
    for name, q in primitives.items():
        s = await _measure(jev, {name: q}, repeats)
        report[name] = {"p50_ms": round(statistics.median(s), 1), "p95_ms": round(_pct(s, 0.95), 1)}
        print(
            f"  1x {name:8}  p50={report[name]['p50_ms']:7.1f}ms  p95={report[name]['p95_ms']:7.1f}ms"
        )

    for n in sizes:
        questions = {f"q{i}": _choice_question(i) for i in range(n)}
        s = await _measure(jev, questions, repeats)
        key = f"choice_x{n}"
        report[key] = {"p50_ms": round(statistics.median(s), 1), "p95_ms": round(_pct(s, 0.95), 1)}
        per = round(statistics.median(s) / n, 1)
        print(
            f"  {n}x choice  p50={report[key]['p50_ms']:7.1f}ms  p95={report[key]['p95_ms']:7.1f}ms"
            f"   per_q={per}ms"
        )

    return {"base_url": jev.base_url, "device": device, "repeats": repeats, "results": report}


def main() -> None:
    parser = argparse.ArgumentParser(description="JEV decision latency benchmark")
    parser.add_argument("--sizes", type=str, default="1,2,4,8,16")
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()

    sizes = [int(x) for x in args.sizes.split(",") if x.strip()]
    result = asyncio.run(run(sizes, args.repeats))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        logger.info("json written", path=args.json)


if __name__ == "__main__":
    main()
