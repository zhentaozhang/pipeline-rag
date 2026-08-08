import json
import types

import pytest

import app.orchestrator.recommendation as recommendation_module
from app.chat.memory import MemoryContext
from app.orchestrator.recommendation import RecommendationService


class FakeResponse:
    def __init__(self, content):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]


class FakeClient:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return FakeResponse(self.content)


def make_settings(enabled=True):
    return types.SimpleNamespace(
        llm=types.SimpleNamespace(model="m"),
        recommendation=types.SimpleNamespace(enabled=enabled, timeout_ms=5000),
    )


class TestGenerateRecommendations:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(recommendation_module, "settings", make_settings(enabled=False))
        svc = RecommendationService()
        assert await svc.generate_recommendations("q", "a", MemoryContext()) == []

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        client = FakeClient(content=json.dumps({"recommendations": ["追问1", "追问2", "追问3", "追问4"]}))
        monkeypatch.setattr(recommendation_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(recommendation_module, "settings", make_settings())
        out = await RecommendationService().generate_recommendations("q", "a", MemoryContext())
        assert out == ["追问1", "追问2", "追问3"]
        assert client.calls[0]["max_tokens"] == 200

    @pytest.mark.asyncio
    async def test_empty_content_returns_empty(self, monkeypatch):
        client = FakeClient(content=None)
        monkeypatch.setattr(recommendation_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(recommendation_module, "settings", make_settings())
        assert await RecommendationService().generate_recommendations("q", "a", MemoryContext()) == []

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(self, monkeypatch):
        client = FakeClient(content="oops")
        monkeypatch.setattr(recommendation_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(recommendation_module, "settings", make_settings())
        assert await RecommendationService().generate_recommendations("q", "a", MemoryContext()) == []

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(self, monkeypatch):
        client = FakeClient(error=RuntimeError("down"))
        monkeypatch.setattr(recommendation_module, "get_chat_client", lambda: client)
        monkeypatch.setattr(recommendation_module, "settings", make_settings())
        assert await RecommendationService().generate_recommendations("q", "a", MemoryContext()) == []
