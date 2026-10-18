"""T0：按请求统计 JEV 调用次数（"每个回答花了多少次判定"是延迟/成本的直接刻度）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _fake_post():
    resp = MagicMock()
    resp.json.return_value = {
        "answers": {"q": {"noul": 0.9}},
        "latency_ms": 1.0,
        "model": "jev-local",
    }
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.asyncio
async def test_calls_are_counted_per_request_and_reset():
    from app.infra import jev_client as jc

    jc.reset_request_jev_calls()
    client = jc.JEVClient()
    with patch("httpx.AsyncClient.post", return_value=_fake_post()) as post:
        await client.system_one("s", {"q": {"type": "noul", "instructions": "i"}})
        await client.system_one("s", {"q": {"type": "noul", "instructions": "i"}})
        await client.aclose()

    assert post.call_count == 2
    assert jc.jev_calls_this_request() == 2

    jc.reset_request_jev_calls()
    assert jc.jev_calls_this_request() == 0


@pytest.mark.asyncio
async def test_empty_questions_do_not_count_as_a_call():
    from app.infra import jev_client as jc

    jc.reset_request_jev_calls()
    client = jc.JEVClient()
    assert await client.system_one("s", {}) == {}
    await client.aclose()
    assert jc.jev_calls_this_request() == 0
