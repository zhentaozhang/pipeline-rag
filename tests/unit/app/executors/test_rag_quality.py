"""质量审核的 fail-open 必须能被观测：passed=True 不等于"审核通过"。

保守口径（用户 2026-10-19 拍板）：不改 passed / 不改线上返回，
只把"没审成"标记为 status="unknown" 供评测与观测单列统计。
"""

from __future__ import annotations

import types

import pytest

import app.executors.rag as rag_module
from app.executors.rag import AnswerQualityChecker


def _settings(**rag):
    defaults = dict(
        quality_enabled=True,
        quality_min_score=8.0,
        quality_check_timeout_seconds=5.0,
        quality_max_retries=1,
    )
    defaults.update(rag)
    return types.SimpleNamespace(rag=types.SimpleNamespace(**defaults))


@pytest.fixture(autouse=True)
def _stub_jev(monkeypatch):
    async def _none(self, question, answer):
        return None

    monkeypatch.setattr(AnswerQualityChecker, "_jev_quality_score", _none)


@pytest.mark.asyncio
async def test_llm_failure_marks_status_unknown(monkeypatch):
    monkeypatch.setattr(rag_module, "settings", _settings())

    class _Broken(AnswerQualityChecker):
        async def _call_llm(self, prompt):
            raise TimeoutError("llm timeout")

    result = await _Broken().check("q", "a" * 40)
    assert result.passed is True  # 保守：线上行为不变
    assert result.status == "unknown"


@pytest.mark.asyncio
async def test_disabled_is_not_confused_with_unknown(monkeypatch):
    monkeypatch.setattr(rag_module, "settings", _settings(quality_enabled=False))
    result = await AnswerQualityChecker().check("q", "a" * 40)
    assert result.passed is True
    assert result.status == "disabled"


@pytest.mark.asyncio
async def test_successful_check_marks_status_checked(monkeypatch):
    monkeypatch.setattr(rag_module, "settings", _settings())

    class _Ok(AnswerQualityChecker):
        async def _call_llm(self, prompt):
            return {"score": 9.0, "issues": [], "suggestion": "", "dimensions": {}}

    result = await _Ok().check("q", "a" * 40)
    assert result.passed is True
    assert result.status == "checked"
