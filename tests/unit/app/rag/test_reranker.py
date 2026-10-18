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
        keep_top_n=0,
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
    monkeypatch.setattr(reranker_module, "settings", make_settings(rerank_settings))
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
    async def test_keep_top_n_truncation(self, reranker, monkeypatch, rerank_settings):
        """本地截断只看 keep_top_n（本地保留条数），与 API 侧 top_n 解耦。"""
        monkeypatch.setattr(rerank_settings, "keep_top_n", 3)
        fake = FakeClient(
            FakeResponse(
                {"results": [{"index": i, "relevance_score": 1.0 - i / 10} for i in range(5)]}
            )
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        result = await reranker.rerank("q", [ev(f"c{i}") for i in range(5)])
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_legacy_top_n_does_not_truncate_locally(self, reranker, monkeypatch):
        """旧配置只写了 top_n 时不得再当截断开关用 —— 那会造成无日志的静默封顶。"""
        fake = FakeClient(
            FakeResponse(
                {"results": [{"index": i, "relevance_score": 1.0 - i / 10} for i in range(5)]}
            )
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        result = await reranker.rerank("q", [ev(f"c{i}") for i in range(5)])
        assert len(result) == 5

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
        fake = FakeClient(FakeResponse({"results": [{"index": 5, "relevance_score": 0.9}]}))
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
        # 请求全部候选分数（截断由本地 top_n 决定）
        assert payload["top_n"] == 1


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

    @pytest.mark.asyncio
    async def test_payload_requests_scores_for_all_documents(self, reranker, monkeypatch):
        """API 侧 top_n 必须等于文档数：否则候选在进入父块提升前就被硬截断。"""
        fake = FakeClient(
            FakeResponse({"results": [{"index": i, "relevance_score": 0.5} for i in range(5)]})
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)
        captured = []
        monkeypatch.setattr(
            reranker_module,
            "_get_rerank_client",
            lambda: FakeClient(fake.response, captured),
        )

        await reranker.rerank("q", [ev(f"c{i}") for i in range(5)])
        assert captured[0][2]["top_n"] == 5

    @pytest.mark.asyncio
    async def test_top_n_zero_keeps_all_results(self, reranker, monkeypatch, rerank_settings):
        monkeypatch.setattr(rerank_settings, "top_n", 0)
        fake = FakeClient(
            FakeResponse(
                {"results": [{"index": i, "relevance_score": 1.0 - i / 10} for i in range(5)]}
            )
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        result = await reranker.rerank("q", [ev(f"c{i}") for i in range(5)])
        assert len(result) == 5

    async def test_score_cap_limits_payload_and_keeps_unscored_tail(
        self, reranker, monkeypatch, rerank_settings
    ):
        """score_cap = "送打分条数上限"：超出部分不送 API，但不得丢弃，追加在已评分之后。"""
        monkeypatch.setattr(rerank_settings, "score_cap", 2, raising=False)
        fake = FakeClient(
            FakeResponse(
                {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.5},
                    ]
                }
            )
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)

        evs = [ev("c1"), ev("c2"), ev("c3"), ev("c4"), ev("c5")]
        out = await reranker.rerank("q", evs)

        sent = fake.captured[0][2]
        assert len(sent["documents"]) == 2
        assert sent["top_n"] == 2
        assert [e.chunk_id for e in out[:2]] == ["c2", "c1"]
        assert [e.chunk_id for e in out[2:]] == ["c3", "c4", "c5"]
        assert all(e.rerank_score == 0.0 for e in out[2:])

    async def test_score_cap_zero_scores_every_candidate(
        self, reranker, monkeypatch, rerank_settings
    ):
        monkeypatch.setattr(rerank_settings, "score_cap", 0, raising=False)
        fake = FakeClient(
            FakeResponse({"results": [{"index": i, "relevance_score": 0.5} for i in range(5)]})
        )
        monkeypatch.setattr(reranker_module, "_get_rerank_client", lambda: fake)
        await reranker.rerank("q", [ev(f"c{i}") for i in range(5)])
        assert len(fake.captured[0][2]["documents"]) == 5
