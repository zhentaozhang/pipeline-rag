import types

import httpx
import pytest

import app.rag.reranker as reranker_module
from app.chat.schema import Evidence
from app.rag.reranker import Reranker


def make_rerank_settings(**overrides):
    defaults = dict(
        enabled=True,
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        model="bge-reranker-v2-m3",
        top_n=3,
        connect_timeout_ms=1000,
        read_timeout_ms=5000,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def make_settings(rerank):
    return types.SimpleNamespace(rerank=rerank)


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, response, captured=None):
        self.response = response
        self.captured = captured if captured is not None else []

    async def post(self, url, headers=None, json=None):
        self.captured.append((url, headers, json))
        return self.response


def ev(chunk_id, content=None):
    return Evidence(
        chunk_id=chunk_id,
        doc_id="doc-1",
        title="t",
        content=content if content is not None else f"内容{chunk_id}",
    )


@pytest.fixture
def rerank_settings():
    return make_rerank_settings()


@pytest.fixture
def reranker(monkeypatch, rerank_settings):
    monkeypatch.setattr(
        reranker_module, "settings", make_settings(rerank_settings)
    )
    return Reranker()


class TestDisabledOrEmpty:
    @pytest.mark.asyncio
    async def test_disabled_returns_input(self, reranker, rerank_settings, monkeypatch):
        monkeypatch.setattr(rerank_settings, "enabled", False)
        evs = [ev("a")]
        assert await reranker.rerank("q", evs) is evs

    @pytest.mark.asyncio
    async def test_empty_evidences_returns_input(self, reranker):
        evs = []
        assert await reranker.rerank("q", evs) is evs


class TestRerankCall:
    @pytest.mark.asyncio
    async def test_payload_and_sorting(self, reranker, monkeypatch):
        fake = FakeClient(
            FakeResponse(
                {
                    "results": [
                        {"index": 0, "relevance_score": 0.3},
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 2, "relevance_score": 0.6},
                    ]
                }
            )
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        evs = [ev("a"), ev("b"), ev("c")]
        result = await reranker.rerank("查询", evs)

        assert [e.chunk_id for e in result] == ["b", "c", "a"]
        assert result[0].rerank_score == 0.9
        assert result[0].rerank_original_index == 1
        assert result[1].rerank_score == 0.6
        assert result[2].rerank_score == 0.3

    @pytest.mark.asyncio
    async def test_metadata_fields(self, reranker, monkeypatch):
        fake = FakeClient(FakeResponse({"results": [{"index": 0, "relevance_score": 0.8}]}))
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        result = await reranker.rerank("查询词", [ev("a")])
        assert result[0].rerank_model == "bge-reranker-v2-m3"
        assert result[0].rerank_query == "查询词"
        assert isinstance(result[0].rerank_duration_ms, int)
        assert result[0].rerank_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_top_n_truncation(self, reranker, monkeypatch):
        fake = FakeClient(
            FakeResponse(
                {
                    "results": [
                        {"index": i, "relevance_score": 1.0 - i / 10}
                        for i in range(5)
                    ]
                }
            )
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        result = await reranker.rerank("q", [ev(f"c{i}") for i in range(5)])
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_original_evidence_not_mutated(self, reranker, monkeypatch):
        fake = FakeClient(FakeResponse({"results": [{"index": 0, "relevance_score": 0.8}]}))
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        evs = [ev("a")]
        result = await reranker.rerank("q", evs)
        assert evs[0].rerank_score == 0.0
        assert evs[0].rerank_query is None
        assert result[0] is not evs[0]

    @pytest.mark.asyncio
    async def test_out_of_range_index_skipped(self, reranker, monkeypatch):
        fake = FakeClient(
            FakeResponse({"results": [{"index": 5, "relevance_score": 0.9}]})
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        result = await reranker.rerank("q", [ev("a")])
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_score_defaults_zero(self, reranker, monkeypatch):
        fake = FakeClient(FakeResponse({"results": [{"index": 0}]}))
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        result = await reranker.rerank("q", [ev("a")])
        assert result[0].rerank_score == 0.0

    @pytest.mark.asyncio
    async def test_payload_contents(self, reranker, monkeypatch):
        captured = []
        fake = FakeClient(
            FakeResponse({"results": [{"index": 0, "relevance_score": 0.5}]}), captured
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        await reranker.rerank("查询", [ev("a", content="内容a")])
        url, headers, payload = captured[0]
        assert url == "https://api.example.com/v1/rerank"
        assert headers["Authorization"] == "Bearer sk-test"
        assert payload["model"] == "bge-reranker-v2-m3"
        assert payload["query"] == "查询"
        assert payload["documents"] == ["内容a"]
        assert payload["top_n"] == 3


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_http_error_propagates(self, reranker, monkeypatch):
        class ErrorResponse:
            def raise_for_status(self):
                raise httpx.HTTPStatusError("500", request=None, response=None)

        fake = FakeClient(ErrorResponse())
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        with pytest.raises(httpx.HTTPStatusError):
            await reranker.rerank("q", [ev("a")])
