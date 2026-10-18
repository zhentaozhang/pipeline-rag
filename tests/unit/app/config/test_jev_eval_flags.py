"""T5：评测指标只允许由大模型判定，JEV 不得接管（默认关 + 显式开启时强制降级）。"""

from __future__ import annotations

import logging

import pytest

_EVAL_FLAGS = (
    "faithfulness_eval_enabled",
    "answer_relevancy_enabled",
    "answer_correctness_enabled",
    "context_precision_enabled",
    "context_recall_enabled",
)


@pytest.mark.parametrize("flag", _EVAL_FLAGS)
def test_evaluation_flags_default_to_off(flag: str):
    from app.config.jev import JEVSettings

    settings = JEVSettings(_env_file=None)
    assert getattr(settings, flag) is False, "评测必须锁定单一强 LLM 裁判，JEV 默认不参与"


def test_enabling_an_evaluation_flag_is_downgraded_with_a_warning(caplog):
    from app.config.jev import JEVSettings

    with caplog.at_level(logging.WARNING, logger="app.config.jev"):
        settings = JEVSettings(_env_file=None, faithfulness_eval_enabled=True)

    assert settings.faithfulness_eval_enabled is False, "显式开启也必须被强制降级"
    assert any("faithfulness_eval_enabled" in r.getMessage() for r in caplog.records)


def test_non_evaluation_flags_are_untouched():
    from app.config.jev import JEVSettings

    settings = JEVSettings(_env_file=None, quality_eval_enabled=True)
    assert settings.quality_eval_enabled is True


def test_dead_intent_helper_is_removed():
    """jev_classify_intent 无任何调用方（双份 prompt 死代码），必须删除而不是继续维护。"""
    from app.orchestrator import intent_detector

    assert not hasattr(intent_detector, "jev_classify_intent")
