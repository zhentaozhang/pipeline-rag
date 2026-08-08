import types

import pytest

import app.common.llm_client as llm_client_module
from app.common.llm_client import llm_breaker


def make_settings(*, same_eval=False):
    llm = types.SimpleNamespace(
        base_url="http://llm",
        api_key="key",
        embedding_base_url="",
        embedding_api_key="",
        timeout_seconds=30,
        model="m",
    )
    rag = types.SimpleNamespace(
        evaluation_base_url="" if same_eval else "http://eval",
        evaluation_api_key="" if same_eval else "eval-key",
        evaluation_timeout_seconds=60,
    )
    return types.SimpleNamespace(llm=llm, rag=rag)


class FakeAsyncOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeAsyncOpenAI.instances.append(kwargs)


def install(monkeypatch, settings=None):
    monkeypatch.setattr(llm_client_module, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(llm_client_module, "settings", settings or make_settings())
    monkeypatch.setattr(llm_client_module, "_chat_client", None)
    monkeypatch.setattr(llm_client_module, "_embedding_client", None)
    monkeypatch.setattr(llm_client_module, "_eval_client", None)
    FakeAsyncOpenAI.instances = []


class TestGetChatClient:
    def test_creates_with_settings(self, monkeypatch):
        install(monkeypatch)
        client = llm_client_module.get_chat_client()
        assert client.kwargs == {
            "base_url": "http://llm",
            "api_key": "key",
            "timeout": 30,
        }

    def test_singleton(self, monkeypatch):
        install(monkeypatch)
        assert llm_client_module.get_chat_client() is llm_client_module.get_chat_client()
        assert len(FakeAsyncOpenAI.instances) == 1


class TestGetEmbeddingClient:
    def test_falls_back_to_llm_settings(self, monkeypatch):
        install(monkeypatch)
        client = llm_client_module.get_embedding_client()
        assert client.kwargs["base_url"] == "http://llm"
        assert client.kwargs["api_key"] == "key"

    def test_custom_embedding_settings(self, monkeypatch):
        settings = make_settings()
        settings.llm.embedding_base_url = "http://embed"
        settings.llm.embedding_api_key = "ekey"
        install(monkeypatch, settings)
        client = llm_client_module.get_embedding_client()
        assert client.kwargs["base_url"] == "http://embed"
        assert client.kwargs["api_key"] == "ekey"


class TestGetEvalClient:
    def test_same_endpoint_reuses_chat_client(self, monkeypatch):
        install(monkeypatch, make_settings(same_eval=True))
        chat = llm_client_module.get_chat_client()
        eval_client = llm_client_module.get_eval_client()
        assert eval_client is chat
        assert len(FakeAsyncOpenAI.instances) == 1

    def test_different_endpoint_creates_own(self, monkeypatch):
        install(monkeypatch)
        eval_client = llm_client_module.get_eval_client()
        assert eval_client.kwargs["base_url"] == "http://eval"
        assert eval_client.kwargs["api_key"] == "eval-key"
        assert eval_client.kwargs["timeout"] == 60

    def test_cached(self, monkeypatch):
        install(monkeypatch)
        assert llm_client_module.get_eval_client() is llm_client_module.get_eval_client()


class TestLlMBreaker:
    @pytest.mark.asyncio
    async def test_context_enters_and_exits(self):
        inside = []

        async def body():
            inside.append(True)

        async with llm_breaker():
            await body()
        assert inside == [True]
