"""
系统健康检查 API

端点：
- GET /health/readiness   — K8s readiness probe（全量探测，无缓存）
- GET /health/liveness    — K8s liveness probe（仅进程存活性）
- GET /health/startup     — K8s startup probe（仅初始化状态）
- GET /health             — 缓存化健康总览（15s TTL）
- GET /health/dependencies — 详细依赖状态（供 Admin Dashboard 使用）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from app.infra.health import (
    check_all,
    invalidate_cache,
    is_startup_complete,
)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_cached() -> JSONResponse:
    """缓存化健康总览（15s TTL），供常规轮询使用。"""
    payload = await check_all()
    status_code = 200 if payload["status"] == "ok" else 503
    return JSONResponse(payload, status_code=status_code)


@router.get("/health/readiness")
async def health_readiness() -> JSONResponse:
    """K8s readiness probe — 全量探测所有下游依赖（不缓存）。"""
    invalidate_cache()
    payload = await check_all()
    status_code = 200 if payload["status"] == "ok" else 503
    return JSONResponse(payload, status_code=status_code)


@router.get("/health/liveness")
async def health_liveness() -> JSONResponse:
    """K8s liveness probe — 仅判断进程存活性。"""
    return JSONResponse({"status": "ok"})


@router.get("/health/startup")
async def health_startup() -> Response:
    """K8s startup probe — 返回 200 仅当所有服务初始化完成。"""
    if is_startup_complete():
        payload = await check_all()
        status_code = 200 if payload["status"] == "ok" else 503
        return JSONResponse(payload, status_code=status_code)
    return JSONResponse(
        {"status": "starting", "startup_complete": False},
        status_code=503,
    )


@router.get("/health/dependencies")
async def health_dependencies() -> JSONResponse:
    """详细依赖状态（带熔断器），供 Admin Dashboard 使用。"""
    invalidate_cache()
    payload = await check_all()
    checks: dict[str, Any] = payload.get("checks", {})
    deps = []
    for name, result in checks.items():
        deps.append(
            {
                "name": name,
                "status": result.get("status", "unknown"),
                "error": result.get("error"),
            }
        )
    return JSONResponse(
        {
            "status": payload.get("status", "unknown"),
            "startup_complete": payload.get("startup_complete", False),
            "dependencies": deps,
            "circuit_breakers": payload.get("circuit_breakers", []),
        }
    )
