"""AnswerQualityChecker 的 JEV Score 路径单测。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.executors.rag import AnswerQualityChecker


def _enable(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings().jev, "quality_eval_enabled", True)


def _patch_jev(answers):
    mock = MagicMock()
    mock.system_one = AsyncMock(return_value=answers)
    return patch("app.infra.jev_client.get_jev_client", return_value=mock)


@pytest.mark.asyncio
async def test_jev_quality_score_maps_level(monkeypatch):
    _enable(monkeypatch)
    checker = AnswerQualityChecker()
    with _patch_jev({"quality": {"score": "优秀：完整、准确、有据且条理清晰", "confidence": 0.9}}):
        score = await checker._jev_quality_score("q", "a")
    assert score == 9.5


@pytest.mark.asyncio
async def test_jev_quality_score_missing_returns_none(monkeypatch):
    _enable(monkeypatch)
    checker = AnswerQualityChecker()
    with _patch_jev({"quality": None}):
        assert await checker._jev_quality_score("q", "a") is None


@pytest.mark.asyncio
async def test_check_passes_via_jev_without_llm(monkeypatch, fake_llm):
    _enable(monkeypatch)
    checker = AnswerQualityChecker()
    with _patch_jev({"quality": {"score": "良好：较完整、准确、基于证据", "confidence": 0.9}}):
        result = await checker.check("q", "一段足够长的回答" * 10)
    assert result.passed is True
    assert result.score == 8.0
    # JEV 通过 → 不应触发 LLM
    assert fake_llm.calls == []


@pytest.mark.asyncio
async def test_check_falls_back_to_llm_when_jev_fails(monkeypatch, fake_llm):
    _enable(monkeypatch)
    checker = AnswerQualityChecker()
    # JEV 判低分 → 继续走 LLM 取问题/建议
    fake_llm.set_fallback(lambda kwargs: '{"score": 3, "issues": ["不完整"], "suggestion": "补充"}')
    with _patch_jev({"quality": {"score": "很差：答非所问或内容空洞", "confidence": 0.9}}):
        result = await checker.check("q", "一段足够长的回答" * 10)
    assert result.passed is False
    assert result.issues == ["不完整"]
    assert fake_llm.calls  # LLM 被调用
