"""AnswerQualityChecker 的 JEV 路径单测。

判据已从"1-10 分档"改为 4 个 yes/no 概率取平均（见 test_quality_criteria.py），
这里验证的是它在 check() 里的接线：够分即免 LLM，不够分回退 LLM 取问题清单。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.executors.rag import AnswerQualityChecker


def _enable(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings().jev, "quality_eval_enabled", True)


def _patch_jev(noul: float):
    """四个判据都给同一个概率，便于控制平均分。"""
    from app.executors.rag import QUALITY_CRITERIA

    answers = {name: {"noul": noul} for name in QUALITY_CRITERIA}
    mock = MagicMock()
    mock.system_one = AsyncMock(return_value=answers)
    return patch("app.infra.jev_client.get_jev_client", return_value=mock)


@pytest.mark.asyncio
async def test_jev_quality_score_is_mean_of_criteria(monkeypatch):
    _enable(monkeypatch)
    checker = AnswerQualityChecker()
    with _patch_jev(0.95):
        score = await checker._jev_quality_score("q", "a")
    assert score == pytest.approx(9.5)


@pytest.mark.asyncio
async def test_jev_quality_score_missing_returns_none(monkeypatch):
    _enable(monkeypatch)
    checker = AnswerQualityChecker()
    with _patch_jev(None):  # 服务端没回分数
        assert await checker._jev_quality_score("q", "a") is None


@pytest.mark.asyncio
async def test_check_passes_via_jev_without_llm(monkeypatch, fake_llm):
    _enable(monkeypatch)
    checker = AnswerQualityChecker()
    with _patch_jev(0.8):
        result = await checker.check("q", "一段足够长的回答" * 10)
    assert result.passed is True
    assert result.score == pytest.approx(8.0)
    # JEV 通过 → 不应触发 LLM
    assert fake_llm.calls == []


@pytest.mark.asyncio
async def test_check_falls_back_to_llm_when_jev_fails(monkeypatch, fake_llm):
    _enable(monkeypatch)
    checker = AnswerQualityChecker()
    # JEV 判低分 → 继续走 LLM 取问题/建议
    fake_llm.set_fallback(lambda kwargs: '{"score": 3, "issues": ["不完整"], "suggestion": "补充"}')
    with _patch_jev(0.2):
        result = await checker.check("q", "一段足够长的回答" * 10)
    assert result.passed is False
    assert result.issues == ["不完整"]
    assert fake_llm.calls  # LLM 被调用
