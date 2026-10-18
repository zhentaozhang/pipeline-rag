"""生成层可复现性：seed 只有在显式配置时才下发，默认不改变线上行为。"""

from __future__ import annotations

import types

import app.executors.rag_stream as stream_module
from app.executors.rag_stream import _seed_kwargs


def test_seed_absent_by_default(monkeypatch):
    monkeypatch.setattr(
        stream_module, "settings", types.SimpleNamespace(llm=types.SimpleNamespace())
    )
    assert _seed_kwargs() == {}


def test_seed_passed_when_configured(monkeypatch):
    monkeypatch.setattr(
        stream_module, "settings", types.SimpleNamespace(llm=types.SimpleNamespace(seed=7))
    )
    assert _seed_kwargs() == {"seed": 7}
