"""
pytest 共享 fixtures。

统一隔离外部依赖：
- monkeypatch get_chat_client 返回全局 fake 客户端，避免真实 LLM / 网络调用
- 全局单例 + 每测试 reset：规避 `from ... import get_chat_client` 模块级绑定
  首次导入即固定引用的问题
- 队列式响应注入，支持顺序返回多个结果
"""

from __future__ import annotations

import json
from typing import Any

import pytest

# 模块级 `from app.common.llm_client import get_chat_client` 会产生各自的绑定，
# 只 patch 源模块无效（能否生效取决于 import 顺序）。这里显式同时 patch 目标模块，
# 保证 fake 隔离不依赖 import 顺序（否则会真调外部 LLM → flaky + 泄漏 key）。
_CHAT_CLIENT_TARGET_MODULES = (
    "app.infra.embedding",
    "app.document.structure.ambiguity",
    "app.rag.channels.vector",
    "app.executors.rag_stream",
    "app.executors.rag",
    "app.executors.aggregator_executor",
    "app.orchestrator.supervisor_graph",
    "app.orchestrator.supervisor",
    "app.orchestrator.recommendation",
    "app.orchestrator.guardrails",
)


class FakeCompletions:
    """可编程的 chat.completions mock（全局单例，每测试 reset）。"""

    _instance: FakeCompletions | None = None

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Message:
            def __init__(self, content: str) -> None:
                self.content = content

        class _Choices:
            def __init__(self, content: str) -> None:
                self.message = _Message(content)

        class _Completions:
            def __init__(self, owner: FakeCompletions) -> None:
                self._owner = owner

            async def create(self, **kwargs: Any) -> Any:
                record = dict(kwargs)
                record.pop("messages", None)
                self._owner.calls.append({"kwargs": kwargs, "record": record})
                if self._owner._responses:
                    content = self._owner._responses.pop(0)
                elif self._owner._fallback is not None:
                    content = self._owner._fallback(kwargs)
                else:
                    raise AssertionError("fake LLM 未配置任何响应队列，请注入 queue/fallback")
                return type("Resp", (), {"choices": [_Choices(content)]})()

        class _Chat:
            def __init__(self, owner: FakeCompletions) -> None:
                self.completions = _Completions(owner)

        self._client = type("FakeClient", (), {})()
        # 部分调用方会读 base_url（如 ambiguity 里的 dashscope 判断）
        self._client.base_url = "https://fake.local/v1"
        self._client.chat = _Chat(self)
        self._responses: list[str] = []
        self._fallback: Any = None
        self.calls: list[dict[str, Any]] = []

        self._install(monkeypatch)

    def _install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """每次测试重新 patch get_chat_client：源模块 + 各目标模块的绑定。

        目标模块用 `from ... import get_chat_client` 持有独立引用，只 patch 源模块会
        漏掉已在导入期绑定真实客户端的模块（真调 LLM）。显式逐个 patch 消除该依赖。
        """
        import importlib

        import app.common.llm_client as llm_client_mod

        replacement = lambda: self._client  # noqa: E731
        monkeypatch.setattr(llm_client_mod, "get_chat_client", replacement)
        for module_path in _CHAT_CLIENT_TARGET_MODULES:
            try:
                module = importlib.import_module(module_path)
            except Exception:  # noqa: BLE001 — 模块不可导入时跳过
                continue
            if hasattr(module, "get_chat_client"):
                monkeypatch.setattr(module, "get_chat_client", replacement, raising=False)

    def reset(self) -> None:
        self._responses.clear()
        self._fallback = None
        self.calls.clear()

    def queue(self, content: str) -> None:
        self._responses.append(content)

    def queue_json(self, obj: dict[str, Any]) -> None:
        self.queue(json.dumps(obj, ensure_ascii=False))

    def set_fallback(self, fn: Any) -> None:
        self._fallback = fn


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeCompletions:
    """全局 fake chat client；每测试重 patch + reset，避免模块级绑定串扰。"""
    if FakeCompletions._instance is None:
        FakeCompletions._instance = FakeCompletions(monkeypatch)
    instance = FakeCompletions._instance
    instance._install(monkeypatch)
    instance.reset()
    return instance