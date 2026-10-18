"""LLM gold 对齐的纯函数部分（候选粗筛 / prompt 构造 / 响应解析）。"""

from __future__ import annotations

from scripts.evaluation.gold_grounding_llm import (
    build_grounding_messages,
    parse_grounding_response,
    prefilter_candidates,
)

CHUNKS = [
    {
        "chunk_id": "1",
        "parent_block_id": "10",
        "section_path": "第5条 试用期规定",
        "chunk_text": "劳动合同期限三个月以上不满一年的，试用期不得超过一个月。",
    },
    {
        "chunk_id": "2",
        "parent_block_id": "10",
        "section_path": "第6条 试用期规定",
        "chunk_text": "劳动合同期限一年以上不满三年的，试用期不得超过二个月。",
    },
    {
        "chunk_id": "3",
        "parent_block_id": "11",
        "section_path": "第9条 年休假",
        "chunk_text": "员工累计工作满1年不满10年的，年休假5天。",
    },
    {
        "chunk_id": "4",
        "parent_block_id": "12",
        "section_path": "第20条 报销",
        "chunk_text": "差旅报销需在出差结束后15个工作日内提交。",
    },
]


class TestPrefilterCandidates:
    def test_most_overlapping_chunk_comes_first(self):
        out = prefilter_candidates("试用期多久", ["试用期不得超过二个月"], CHUNKS)
        assert out[0]["chunk_id"] == "2"

    def test_respects_top_k(self):
        out = prefilter_candidates("试用期", [], CHUNKS, top_k=2)
        assert len(out) == 2

    def test_no_duplicate_candidates(self):
        out = prefilter_candidates("年休假5天", ["年休假5天"], CHUNKS, top_k=10)
        ids = [c["chunk_id"] for c in out]
        assert len(ids) == len(set(ids))

    def test_drops_zero_score_chunks(self):
        out = prefilter_candidates("完全不相关的问句", [], CHUNKS)
        assert all(c["chunk_id"] != "4" for c in out)

    def test_empty_chunks(self):
        assert prefilter_candidates("q", ["a"], []) == []

    def test_question_only_still_ranks(self):
        out = prefilter_candidates("年休假", [], CHUNKS)
        assert out[0]["chunk_id"] == "3"


class TestBuildGroundingMessages:
    def test_lists_all_candidate_ids(self):
        msgs = build_grounding_messages("问题", CHUNKS)
        user = msgs[-1]["content"]
        for chunk in CHUNKS:
            assert f'chunk_id="{chunk["chunk_id"]}"' in user

    def test_instructs_empty_array_when_no_evidence(self):
        msgs = build_grounding_messages("问题", CHUNKS)
        assert "[]" in msgs[0]["content"]

    def test_truncates_long_text(self):
        long_chunk = [{"chunk_id": "9", "parent_block_id": "1", "chunk_text": "字" * 2000}]
        user = build_grounding_messages("问题", long_chunk)[-1]["content"]
        assert "…" in user
        assert len(user) < 1200

    def test_forbids_inventing_ids(self):
        msgs = build_grounding_messages("问题", CHUNKS)
        assert "禁止编造" in msgs[0]["content"]


class TestParseGroundingResponse:
    def test_plain_json_object(self):
        assert parse_grounding_response('{"chunk_ids": ["1", "3"]}', {"1", "3"}) == ["1", "3"]

    def test_code_fenced_json(self):
        text = '```json\n{"chunk_ids": ["2"]}\n```'
        assert parse_grounding_response(text, {"2"}) == ["2"]

    def test_bare_array(self):
        assert parse_grounding_response('["2", "3"]', {"2", "3"}) == ["2", "3"]

    def test_object_items_with_chunk_id(self):
        text = '{"chunk_ids": [{"chunk_id": "1"}]}'
        assert parse_grounding_response(text, {"1"}) == ["1"]

    def test_invalid_ids_are_dropped(self):
        assert parse_grounding_response('{"chunk_ids": ["1", "999"]}', {"1"}) == ["1"]

    def test_empty_array(self):
        assert parse_grounding_response("[]", {"1"}) == []

    def test_garbage_returns_empty(self):
        assert parse_grounding_response("我不知道", {"1"}) == []

    def test_none_returns_empty(self):
        assert parse_grounding_response(None, {"1"}) == []

    def test_fallback_scrapes_numeric_ids_from_broken_json(self):
        text = "chunk_ids: 1, 2 是相关片段"
        assert parse_grounding_response(text, {"1", "2"}) == ["1", "2"]

    def test_dedupes_repeated_ids(self):
        assert parse_grounding_response('["1", "1"]', {"1"}) == ["1"]
