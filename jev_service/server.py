"""
JEV System One 本地决策微服务 FastAPI 入口
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

try:
    from jev_service.batching import MicroBatcher
    from jev_service.judger import LocalJEVJudger
    from jev_service.model_loader import get_device, get_model_and_tokenizer
    from jev_service.schemas import SystemOneRequest, SystemOneResponse
except ImportError:
    from batching import MicroBatcher
    from judger import LocalJEVJudger
    from model_loader import get_device, get_model_and_tokenizer
    from schemas import SystemOneRequest, SystemOneResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("jev_service.server")

judger: LocalJEVJudger | None = None
_batcher: MicroBatcher | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global judger, _batcher
    logger.info("Initializing JEV service...")
    model, tokenizer = get_model_and_tokenizer()
    device = get_device()
    judger = LocalJEVJudger(model=model, tokenizer=tokenizer, device=device)

    # 微批调度：替代原先的全局锁（队列化 + 可观测），默认**不合并**——实测在 MPS 上
    # 合并无吞吐收益（prefill 计算量不变，8 行已是 809ms/行，16 行掉到 1270ms/行），
    # 只有 GPU（A100 级）批处理才值得把 JEV_BATCH_MAX/WINDOW 调大。
    window_ms = float(os.getenv("JEV_BATCH_WINDOW_MS", "0") or 0)
    max_batch = int(os.getenv("JEV_BATCH_MAX", "1") or 1)
    _batcher = MicroBatcher(
        run=lambda batch: judger.judge_entries_multi(batch),
        window_ms=window_ms,
        max_batch=max_batch,
    )
    await _batcher.start()
    logger.info("JEV micro-batcher started (window_ms=%.0f, max_batch=%d)", window_ms, max_batch)

    # 预热前向推理，初始化 CUDA/MPS 显存分配器并预热 PyTorch 算子，消除首次真实请求的 500ms 冷启动延迟
    try:
        logger.info("Warming up JEV inference engine...")
        judger.judge_noul(state="warmup", instructions="warmup")
        logger.info("JEV inference engine warmed up successfully.")
    except Exception as exc:
        logger.warning("JEV warmup warning (non-fatal): %s", exc)

    logger.info("JEV service initialized and ready to serve.")
    yield
    if _batcher is not None:
        await _batcher.close()
    logger.info("JEV service shutting down.")


app = FastAPI(
    title="JEV System One Local Decision Service",
    description="开源免费 System 1 判断模型服务，基于单 Pass Logits 抽取，无需自回归文本生成。",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    model_name = os.getenv("JEV_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
    is_ready = judger is not None
    payload = {
        "status": "healthy" if is_ready else "initializing",
        "service": "jev-service",
        "model": model_name,
        "device": get_device(),
    }
    # 初始化中返回 503，确保 Docker/K8s 探针（如 curl -f）准确感知准备状态，防止过早接收流量
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)


@app.post("/v1/systemone", response_model=SystemOneResponse)
async def system_one(request: SystemOneRequest):
    if judger is None or _batcher is None:
        raise HTTPException(status_code=503, detail="JEV Judger not initialized yet.")

    # 防御性负载校验，防止超大请求导致长时间锁占用或内存膨胀
    if len(request.questions) > 50:
        raise HTTPException(
            status_code=400,
            detail=f"Too many questions in single request (max 50, got {len(request.questions)})",
        )
    if len(request.state) > 50000:
        raise HTTPException(
            status_code=400,
            detail=f"State payload too large (max 50,000 chars, got {len(request.state)})",
        )

    t0 = time.perf_counter()
    try:
        # 交给微批调度器：同窗口内的并发请求合并成一次前向，60s 硬超时兜底防挂起
        answers = await asyncio.wait_for(
            _batcher.submit(request.state, request.questions), timeout=60.0
        )
        duration_ms = (time.perf_counter() - t0) * 1000
        return SystemOneResponse(
            answers=answers,
            latency_ms=round(duration_ms, 2),
            model=request.model or "jev-local",
        )
    except TimeoutError:
        logger.error("JEV inference timed out after 60 seconds")
        raise HTTPException(
            status_code=504, detail="JEV decision execution timed out (60s)"
        ) from None
    except Exception as exc:
        logger.exception("Error executing JEV decision: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8080, log_level="info")
