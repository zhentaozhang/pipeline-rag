"""评测生成温度必须可与线上分离：线上 0.5，评测要可复现。"""

from __future__ import annotations

import types

import scripts.evaluation.runner as runner_module


def _settings(**llm):
    defaults = {"temperature": 0.5, "eval_temperature": None}
    defaults.update(llm)
    return types.SimpleNamespace(llm=types.SimpleNamespace(**defaults))


def test_falls_back_to_production_temperature(monkeypatch):
    monkeypatch.setattr(runner_module, "settings", _settings())
    assert runner_module._generation_temperature() == 0.5


def test_prefers_eval_temperature(monkeypatch):
    monkeypatch.setattr(runner_module, "settings", _settings(eval_temperature=0.0))
    assert runner_module._generation_temperature() == 0.0
