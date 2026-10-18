"""JEV 覆盖率埋点（P0-1）：必须能证明"这次决策真的是 JEV 做的"。

为什么需要：JEV 服务挂掉或开关没开时，`jev_decide` 全部走 fail-open 回退到 LLM，
此时跑 V3 与跑 V2 完全等价，但报告上看不出任何区别——这正是上一轮"V3 实测零差异"的根因。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.infra.jev_client import jev_coverage, jev_decide, reset_jev_coverage


@pytest.fixture(autouse=True)
def _clean():
    reset_jev_coverage()
    yield
    reset_jev_coverage()


def _settings(**flags):
    return SimpleNamespace(jev=SimpleNamespace(**flags))


def _answers(value=True):
    return {"is_true": {"is_true": value, "noul": 0.9, "confidence": 0.9}}


def _parse(answers):
    return answers["is_true"]["is_true"]


class _FakeClient:
    def __init__(self, *, answers=None, error: Exception | None = None):
        self._answers = answers if answers is not None else _answers()
        self._error = error

    async def system_one(self, state, questions):
        if self._error is not None:
            raise self._error
        return self._answers


@pytest.mark.asyncio
async def test_disabled_flag_is_counted_as_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.infra.jev_client.get_settings", lambda: _settings(evidence_sufficiency_enabled=False)
    )
    result = await jev_decide("evidence_sufficiency_enabled", "s", {"q": {}}, _parse)
    assert result is None
    cov = jev_coverage()
    assert cov["flags"]["evidence_sufficiency_enabled"]["disabled"] == 1
    assert cov["totals"]["decided"] == 0


@pytest.mark.asyncio
async def test_successful_decision_is_counted(monkeypatch):
    monkeypatch.setattr(
        "app.infra.jev_client.get_settings", lambda: _settings(evidence_sufficiency_enabled=True)
    )
    monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: _FakeClient())
    result = await jev_decide("evidence_sufficiency_enabled", "s", {"q": {}}, _parse)
    assert result is True
    cov = jev_coverage()
    assert cov["flags"]["evidence_sufficiency_enabled"]["decided"] == 1
    assert cov["totals"]["decided"] == 1
    assert cov["flags"]["evidence_sufficiency_enabled"]["calls"] == 1
    assert cov["flags"]["evidence_sufficiency_enabled"]["p50_ms"] is not None


@pytest.mark.asyncio
async def test_client_error_is_counted_as_failed(monkeypatch):
    monkeypatch.setattr(
        "app.infra.jev_client.get_settings", lambda: _settings(evidence_sufficiency_enabled=True)
    )
    monkeypatch.setattr(
        "app.infra.jev_client.get_jev_client",
        lambda: _FakeClient(error=RuntimeError("connection refused")),
    )
    result = await jev_decide("evidence_sufficiency_enabled", "s", {"q": {}}, _parse)
    assert result is None
    cov = jev_coverage()
    assert cov["flags"]["evidence_sufficiency_enabled"]["failed"] == 1
    assert cov["totals"]["decided"] == 0


@pytest.mark.asyncio
async def test_parse_error_is_counted_as_failed(monkeypatch):
    monkeypatch.setattr(
        "app.infra.jev_client.get_settings", lambda: _settings(evidence_sufficiency_enabled=True)
    )
    monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: _FakeClient(answers={}))

    def _boom(answers):
        raise KeyError("is_true")

    assert await jev_decide("evidence_sufficiency_enabled", "s", {"q": {}}, _boom) is None
    assert jev_coverage()["totals"]["failed"] == 1


def test_reset_clears_counters():
    reset_jev_coverage()
    assert jev_coverage()["totals"]["attempted"] == 0
