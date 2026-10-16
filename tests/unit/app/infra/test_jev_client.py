"""
JEV 决策服务客户端与原语单测
"""

from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import REGISTRY

from app.infra.jev_client import JEVClient, get_jev_client


@pytest.mark.asyncio
async def test_jev_client_singleton():
    client1 = get_jev_client()
    client2 = get_jev_client()
    assert client1 is client2
    assert isinstance(client1, JEVClient)


@pytest.mark.asyncio
async def test_jev_client_system_one_call():
    mock_response = {
        "answers": {
            "is_safe": {"noul": 0.98, "is_true": True, "confidence": 0.98},
            "intent": {"choice": "document_qa", "confidence": 0.92},
            "score": {"score": "高", "confidence": 0.89},
        },
        "latency_ms": 45.2,
        "model": "jev-local",
    }

    client = JEVClient()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp_obj = MagicMock()
        mock_resp_obj.json.return_value = mock_response
        mock_resp_obj.raise_for_status.return_value = None
        mock_post.return_value = mock_resp_obj

        res = await client.system_one(
            state="测试状态",
            questions={
                "is_safe": {"type": "noul", "instructions": "是否安全"},
            },
        )
        assert res["is_safe"]["noul"] == 0.98
        assert res["intent"]["choice"] == "document_qa"

        # 测试客户端连接池复用与 aclose 生命周期
        assert client._client is not None
        await client.aclose()
        assert client._client is None


def _reset_jev_breaker() -> None:
    from app.infra.circuit_breaker import CircuitState
    from app.infra.jev_client import _jev_breaker

    _jev_breaker._state = CircuitState.CLOSED
    _jev_breaker._failure_count = 0


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.mark.asyncio
async def test_jev_client_success_metrics():
    _reset_jev_breaker()
    client = JEVClient()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp_obj = MagicMock()
        mock_resp_obj.json.return_value = {"answers": {"a": {"noul": 1.0}}}
        mock_resp_obj.raise_for_status.return_value = None
        mock_post.return_value = mock_resp_obj

        before_success = _sample("safety_jev_jev_call_total", {"outcome": "success"})
        before_latency = _sample("safety_jev_jev_call_latency_seconds_count")
        before_noul = _sample("safety_jev_jev_questions_total", {"type": "noul"})
        before_choice = _sample("safety_jev_jev_questions_total", {"type": "choice"})
        before_score = _sample("safety_jev_jev_questions_total", {"type": "score"})

        res = await client.system_one(
            state="s",
            questions={
                "is_safe": {"type": "noul"},
                "intent": {"type": "choice"},
                "quality": {"type": "score"},
            },
        )
        await client.aclose()

    assert res == {"a": {"noul": 1.0}}
    assert _sample("safety_jev_jev_call_total", {"outcome": "success"}) == before_success + 1
    assert _sample("safety_jev_jev_call_latency_seconds_count") == before_latency + 1
    assert _sample("safety_jev_jev_questions_total", {"type": "noul"}) == before_noul + 1
    assert _sample("safety_jev_jev_questions_total", {"type": "choice"}) == before_choice + 1
    assert _sample("safety_jev_jev_questions_total", {"type": "score"}) == before_score + 1


@pytest.mark.asyncio
async def test_jev_client_empty_questions_metric():
    _reset_jev_breaker()
    client = JEVClient()
    before_empty = _sample("safety_jev_jev_call_total", {"outcome": "empty"})

    res = await client.system_one(state="test", questions={})

    assert res == {}
    assert _sample("safety_jev_jev_call_total", {"outcome": "empty"}) == before_empty + 1


@pytest.mark.asyncio
async def test_jev_client_error_metrics():
    _reset_jev_breaker()
    import httpx

    client = JEVClient()
    before_error = _sample("safety_jev_jev_call_total", {"outcome": "error"})
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("boom")):
        with pytest.raises(httpx.ConnectError):
            await client.system_one(state="s", questions={"q": {"type": "noul"}})
        await client.aclose()

    assert _sample("safety_jev_jev_call_total", {"outcome": "error"}) == before_error + 1


def test_jev_schemas():
    from jev_service.schemas import QuestionItem, SystemOneRequest, SystemOneResponse

    q = QuestionItem(type="noul", instructions="测试指令")
    req = SystemOneRequest(state="内容", questions={"q1": q})
    assert req.questions["q1"].type == "noul"

    resp = SystemOneResponse(
        answers={"q1": {"noul": 0.9}},
        latency_ms=12.5,
        model="jev-local",
    )
    assert resp.answers["q1"]["noul"] == 0.9


@pytest.mark.asyncio
async def test_jev_client_empty_questions():
    client = JEVClient()
    res = await client.system_one(state="test", questions={})
    assert res == {}


@pytest.mark.asyncio
async def test_jev_circuit_breaker_protection():
    import contextlib

    import httpx

    from app.infra.jev_client import _jev_breaker

    client = JEVClient()
    # 模拟 HTTP 连续失败
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
        for _ in range(3):
            with contextlib.suppress(Exception):
                await client.system_one(state="test", questions={"q": {"type": "noul"}})

    # 验证熔断器已在失败后自动记录
    assert _jev_breaker._failure_count >= 1


@pytest.mark.asyncio
async def test_server_health_check_codes():
    pytest.importorskip("torch", reason="torch is installed in jev_service container")
    from unittest.mock import patch

    from jev_service import server

    # 1. 模拟尚未初始化完成 (judger is None) -> 503
    with patch.object(server, "judger", None):
        resp = await server.health_check()
        assert resp.status_code == 503
        import json

        data = json.loads(resp.body.decode())
        assert data["status"] == "initializing"

    # 2. 模拟初始化完成 (judger is not None) -> 200
    mock_judger = MagicMock()
    with patch.object(server, "judger", mock_judger):
        resp = await server.health_check()
        assert resp.status_code == 200
        data = json.loads(resp.body.decode())
        assert data["status"] == "healthy"


def test_model_loader_cache_permission_fallback(tmp_path):
    pytest.importorskip("torch", reason="torch is installed in jev_service container")
    import os

    from jev_service.model_loader import _ensure_cache_dir

    # 模拟不可写路径
    invalid_path = "/root/non_existent_or_protected/cache"
    with patch.dict(os.environ, {"HF_HOME": invalid_path}):
        fallback = _ensure_cache_dir()
        assert fallback is not None
        assert "huggingface" in fallback


def test_jev_client_dynamic_base_url(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings.jev, "base_url", "http://custom-jev:9090")
    client = JEVClient()
    assert client.base_url == "http://custom-jev:9090"


@pytest.mark.asyncio
async def test_server_payload_limits():
    pytest.importorskip("torch", reason="torch is installed in jev_service container")
    from fastapi import HTTPException

    from jev_service import server
    from jev_service.schemas import QuestionItem, SystemOneRequest

    mock_judger = MagicMock()
    with (
        patch.object(server, "judger", mock_judger),
        patch.object(server, "_inference_lock", MagicMock()),
    ):
        # 1. 超过 50 个问题拦截
        too_many_questions = {f"q_{i}": QuestionItem(type="noul") for i in range(51)}
        req = SystemOneRequest(state="test", questions=too_many_questions)
        with pytest.raises(HTTPException) as exc_info:
            await server.system_one(req)
        assert exc_info.value.status_code == 400

        # 2. 超长 state 拦截 (> 50,000)
        req_large = SystemOneRequest(state="A" * 50001, questions={"q": QuestionItem(type="noul")})
        with pytest.raises(HTTPException) as exc_info2:
            await server.system_one(req_large)
        assert exc_info2.value.status_code == 400
