import json
import types

import pytest

import app.orchestrator.classifier as classifier_module
from app.chat.memory import MemoryContext
from app.orchestrator.classifier import IntentClassifier


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


@pytest.fixture
def make_classifier(monkeypatch):
    def install(content=None, error=None):
        client = FakeClient(content=content, error=error)
        monkeypatch.setattr(
            classifier_module,
            "get_chat_client",
            lambda: client,
        )
        monkeypatch.setattr(
            classifier_module,
            "settings",
            types.SimpleNamespace(llm=types.SimpleNamespace(model="m")),
        )
        return IntentClassifier(), client

    return install


class TestClassify:
    @pytest.mark.asyncio
    async def test_knowledge(self, make_classifier):
        classifier, client = make_classifier(content=json.dumps({"intent": "knowledge", "reason": "r"}))
        out = await classifier.classify("如何配置", MemoryContext())
        assert out == "knowledge"
        assert client.calls[0]["model"] == "m"
        assert client.calls[0]["temperature"] == 0.1
        assert client.calls[0]["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_open(self, make_classifier):
        classifier, _ = make_classifier(content=json.dumps({"intent": "open", "reason": "r"}))
        assert await classifier.classify("天气", MemoryContext()) == "open"

    @pytest.mark.asyncio
    async def test_ambiguous(self, make_classifier):
        classifier, _ = make_classifier(content=json.dumps({"intent": "ambiguous"}))
        assert await classifier.classify("那个", MemoryContext()) == "ambiguous"

    @pytest.mark.asyncio
    async def test_invalid_intent_falls_back_knowledge(self, make_classifier):
        classifier, _ = make_classifier(content=json.dumps({"intent": "weird"}))
        assert await classifier.classify("q", MemoryContext()) == "knowledge"

    @pytest.mark.asyncio
    async def test_missing_intent_defaults_knowledge(self, make_classifier):
        classifier, _ = make_classifier(content=json.dumps({"other": 1}))
        assert await classifier.classify("q", MemoryContext()) == "knowledge"

    @pytest.mark.asyncio
    async def test_empty_content_raises_fallback(self, make_classifier):
        classifier, _ = make_classifier(content=None)
        assert await classifier.classify("q", MemoryContext()) == "knowledge"

    @pytest.mark.asyncio
    async def test_invalid_json_fallback(self, make_classifier):
        classifier, _ = make_classifier(content="not json")
        assert await classifier.classify("q", MemoryContext()) == "knowledge"

    @pytest.mark.asyncio
    async def test_llm_error_fallback(self, make_classifier):
        classifier, _ = make_classifier(error=RuntimeError("llm down"))
        assert await classifier.classify("q", MemoryContext()) == "knowledge"
