
from app.chat.schema import Evidence
from app.rag.fusion import rrf_fusion


def ev(chunk_id, score=1.0, channel="vector"):
    return Evidence(
        chunk_id=chunk_id,
        doc_id="doc-1",
        title="t",
        content=f"内容{chunk_id}",
        score=score,
        channel=channel,
    )


def rrf(k, rank):
    return round(1.0 / (k + rank + 1), 6)


def rrf_sum(*values):
    return round(sum(values), 6)


class TestRrfFusion:
    def test_empty_inputs(self):
        assert rrf_fusion([], []) == []

    def test_single_channel(self):
        hits = [ev("a"), ev("b")]
        result = rrf_fusion(hits, [])
        assert [e.chunk_id for e in result] == ["a", "b"]
        assert result[0].channel == "vector"
        assert result[0].rrf_score == rrf(60, 0)

    def test_two_channels_merge_same_chunk(self):
        vector = [ev("a")]
        keyword = [ev("a")]
        result = rrf_fusion(vector, keyword)
        assert len(result) == 1
        assert result[0].channel == "hybrid"
        assert result[0].rrf_score == rrf_sum(1 / 61, 1 / 61)

    def test_rank_bonus(self):
        vector = [ev("a"), ev("b")]
        keyword = []
        result = rrf_fusion(vector, keyword)
        scores = {e.chunk_id: e.rrf_score for e in result}
        assert scores["a"] == rrf(60, 0)
        assert scores["b"] == rrf(60, 1)

    def test_ranking_by_merged_score(self):
        vector = [ev("a")]
        keyword = [ev("a"), ev("b")]
        result = rrf_fusion(vector, keyword)
        assert [e.chunk_id for e in result] == ["a", "b"]
        assert result[0].rrf_score == rrf_sum(1 / 61, 1 / 61)
        assert result[1].rrf_score == rrf(60, 1)

    def test_evidence_not_mutated(self):
        vector = [ev("a")]
        keyword = [ev("a")]
        result = rrf_fusion(vector, keyword)
        assert vector[0].score == 1.0
        assert vector[0].rrf_score == 0.0
        assert vector[0].channel == "vector"
        assert result[0].rrf_score == rrf_sum(1 / 61, 1 / 61)
        assert result[0].channel == "hybrid"
        assert result[0] is not vector[0]

    def test_keyword_only_channel(self):
        result = rrf_fusion([], [ev("k", channel="keyword")])
        assert result[0].channel == "keyword"
        assert result[0].score == rrf(60, 0)
        assert result[0].rrf_score == rrf(60, 0)

    def test_custom_k(self):
        result = rrf_fusion([ev("a")], [], k=10)
        assert result[0].rrf_score == rrf(10, 0)

    def test_original_score_preserved(self):
        vector = [Evidence(
            chunk_id="a",
            doc_id="doc-1",
            title="t",
            content="内容a",
            score=0.9,
            original_score=0.7,
        )]
        result = rrf_fusion(vector, [])
        assert result[0].score == rrf(60, 0)
        assert result[0].original_score == 0.7
