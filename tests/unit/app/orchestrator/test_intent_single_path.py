"""T4：意图判定单路径化——同一标签映射、JEV 灰区回退、可观测 intent_source。"""

from __future__ import annotations

import pytest


class _JevStub:
    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    async def system_one(self, state, questions):
        self.calls += 1
        return self.answers


def _rewriter():
    from app.orchestrator.query_rewriter import ChatQueryRewriteService

    return ChatQueryRewriteService()


@pytest.mark.asyncio
async def test_confident_jev_choice_is_used_and_tagged(monkeypatch):
    from app.orchestrator import query_rewriter as qr

    stub = _JevStub(
        {
            "intent": {
                "choice": "knowledge",
                "confidence": 0.92,
                "distribution": {
                    "knowledge": 0.92,
                    "open": 0.05,
                    "capability": 0.02,
                    "ambiguous": 0.01,
                },
            }
        }
    )
    monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: stub)
    monkeypatch.setattr(qr.settings.jev, "intent_detection_enabled", True, raising=False)

    intent, source = await _rewriter()._resolve_intent("试用期多久？")
    assert intent == "knowledge"
    assert source == "jev"


@pytest.mark.asyncio
async def test_grey_band_falls_back_to_rules(monkeypatch):
    """knowledge 0.46 vs open 0.44 —— 差 2pp 不该硬判，必须回退规则并标注来源。"""
    from app.orchestrator import query_rewriter as qr

    stub = _JevStub(
        {
            "intent": {
                "choice": "knowledge",
                "confidence": 0.46,
                "distribution": {
                    "knowledge": 0.46,
                    "open": 0.44,
                    "capability": 0.06,
                    "ambiguous": 0.04,
                },
            }
        }
    )
    monkeypatch.setattr("app.infra.jev_client.get_jev_client", lambda: stub)
    monkeypatch.setattr(qr.settings.jev, "intent_detection_enabled", True, raising=False)

    intent, source = await _rewriter()._resolve_intent("今天天气怎么样")
    assert intent == "open", "灰区应交给规则层（天气类问题规则判 open）"
    assert source == "rule"


@pytest.mark.asyncio
async def test_rule_source_when_jev_disabled(monkeypatch):
    from app.orchestrator import query_rewriter as qr

    monkeypatch.setattr(qr.settings.jev, "intent_detection_enabled", False, raising=False)
    intent, source = await _rewriter()._resolve_intent("试用期多久？")
    assert intent == "knowledge"
    assert source == "rule"


@pytest.mark.asyncio
async def test_llm_intent_uses_the_same_label_mapping(monkeypatch):
    """LLM 路径返回 capability 时必须与 JEV 路径一样归一为 open，而不是兜 knowledge。"""
    parsed = {
        "rewrite": "问题",
        "should_split": False,
        "sub_questions": [],
        "keywords": [],
        "intent": "capability",
    }
    from app.orchestrator.query_rewriter import ChatQueryRewriteService

    result = ChatQueryRewriteService()._normalize_rewrite_result("原始问题", parsed)
    assert result is not None
    assert result.intent == "open"
    assert result.intent_source == "llm"
