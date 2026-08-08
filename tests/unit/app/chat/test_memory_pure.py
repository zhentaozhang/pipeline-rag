"""chat 层纯逻辑测试：memory 纯函数、TranscriptRenderer、service_utils（无 DB/LLM）。"""

import asyncio
from datetime import datetime

import pytest

from app.chat.memory import (
    MAX_ITEM_LENGTH,
    ConversationSummaryPayload,
    MemoryContext,
    NoMemoryStrategy,
    SlidingWindowStrategy,
    SummaryCompressionStrategy,
    create_memory_strategy,
    deduplicate_and_limit,
    extract_retrieval_hints,
)
from app.chat.service_utils import (
    _async_generator_with_timeout,
    _build_error_message,
    _estimate_tokens,
    _format_current_date,
    _normalize_conversation_id,
    _normalize_question,
)
from app.chat.transcript_renderer import (
    HistoryTurn,
    TranscriptRenderer,
    clip_recent_transcript,
    clip_text,
)
from app.common.exceptions import PipelineRAGBaseException


class TestDeduplicateAndLimit:
    def test_keeps_order_and_deduplicates(self):
        assert deduplicate_and_limit(["a", "b", "a", "c"]) == ["a", "b", "c"]

    def test_strips_and_drops_empty(self):
        assert deduplicate_and_limit(["  x  ", "", "  ", "x"]) == ["x"]

    def test_clips_long_values(self):
        long_text = "长" * (MAX_ITEM_LENGTH + 20)
        result = deduplicate_and_limit([long_text])
        assert len(result) == 1
        assert result[0].endswith("…")
        assert len(result[0]) <= MAX_ITEM_LENGTH

    def test_respects_max_section_items(self):
        values = [f"item-{i}" for i in range(500)]
        result = deduplicate_and_limit(values)
        assert len(result) <= len(values) and len(result) > 0


class TestExtractRetrievalHints:
    def test_empty_question_returns_empty(self):
        assert extract_retrieval_hints("") == []
        assert extract_retrieval_hints(None) == []
        assert extract_retrieval_hints("   ") == []

    def test_extracts_english_and_numbers(self):
        hints = extract_retrieval_hints("RAG 的 chunk_size 是 512 吗？")
        assert "RAG" in hints
        assert "chunk_size" in hints

    def test_extracts_chinese_terms(self):
        hints = extract_retrieval_hints("如何配置向量数据库")
        assert "如何配置向量数据库" in hints

    def test_filters_noise_words(self):
        hints = extract_retrieval_hints("请问 帮我 一下 如何 配置")
        for noise in ("请问", "帮我", "一下", "如何"):
            assert noise not in hints


class TestClipText:
    def test_short_text_unchanged(self):
        assert clip_text("hello", 100) == "hello"

    def test_long_text_gets_ellipsis(self):
        result = clip_text("x" * 50, 10)
        assert result == "x" * 9 + "…"

    def test_none_becomes_empty(self):
        assert clip_text(None, 10) == ""


class TestClipRecentTranscript:
    def test_short_text_unchanged(self):
        assert clip_recent_transcript("hello", 100) == "hello"

    def test_long_text_keeps_tail(self):
        result = clip_recent_transcript("x" * 50, 10)
        assert result == "…" + "x" * 9


class TestTranscriptRenderer:
    def test_render_recent_transcript_empty(self):
        assert TranscriptRenderer.render_recent_transcript([]) == ""

    def test_render_recent_transcript_formats_turns(self):
        text = TranscriptRenderer.render_recent_transcript(
            [HistoryTurn("今天天气如何？", "今天晴朗。")]
        )
        assert "【最近对话原文】" in text
        assert "用户：今天天气如何？" in text
        assert "助手：今天晴朗。" in text

    def test_render_skips_empty_question_and_answer(self):
        text = TranscriptRenderer.render_recent_transcript(
            [HistoryTurn("", ""), HistoryTurn("q", "a")]
        )
        assert "用户：q" in text
        assert "助手：a" in text

    def test_render_answer_recent_transcript_only_questions(self):
        text = TranscriptRenderer.render_answer_recent_transcript([HistoryTurn("q1", "a1")])
        assert "【最近相关对话】" in text
        assert "用户：q1" in text
        assert "a1" not in text

    def test_render_compression_transcript(self):
        text = TranscriptRenderer.render_compression_transcript([HistoryTurn("q", "a")])
        assert "用户：q" in text and "助手：a" in text

    def test_assemble_history_joins_nonempty(self):
        assert TranscriptRenderer.assemble_history("sum", "") == "sum"
        assert TranscriptRenderer.assemble_history("", "") == ""
        assert TranscriptRenderer.assemble_history("a", "b") == "a\n\nb"


class TestEstimateTokens:
    def test_cjk_weighs_more(self):
        assert _estimate_tokens("中文测试") > _estimate_tokens("abcd")

    def test_ascii_estimation(self):
        assert _estimate_tokens("a" * 4) == 1

    def test_empty_string_zero(self):
        assert _estimate_tokens("") == 0


class TestFormatCurrentDate:
    def test_formats_weekday(self):
        d = datetime(2026, 8, 7)
        assert _format_current_date(d) == "2026-08-07（星期五）"


class TestNormalizeQuestion:
    def test_strips_whitespace(self):
        assert _normalize_question("  你好  ") == "你好"

    def test_empty_raises(self):
        with pytest.raises(PipelineRAGBaseException):
            _normalize_question("  ")


class TestNormalizeConversationId:
    def test_preserves_valid_id(self):
        assert _normalize_conversation_id("conv-1") == "conv-1"

    def test_generates_hex_uuid_when_missing(self):
        cid = _normalize_conversation_id(None)
        assert len(cid) == 32
        assert all(c in "0123456789abcdef" for c in cid)


class TestBuildErrorMessage:
    def test_plain_exception_message(self):
        assert _build_error_message(ValueError("boom")) == "boom"

    def test_empty_message_falls_back_to_type_name(self):
        assert _build_error_message(ValueError("")) == "ValueError"

    def test_chained_http_error_uses_response_body(self):
        outer = RuntimeError("outer")

        class FakeHTTPError(Exception):
            def __init__(self):
                super().__init__("raw")
                self.status_code = 500
                self.response_body = "{\"error\": \"bad\"}"
                self.request_method = "POST"
                self.request_url = "http://x/api"

        inner = FakeHTTPError()
        outer.__cause__ = inner
        msg = _build_error_message(outer)
        assert "500" in msg and "bad" in msg and "POST" in msg


class TestAsyncGeneratorWithTimeout:
    async def test_yields_all_items(self):
        async def gen():
            yield "a"
            yield "b"

        out = [item async for item in _async_generator_with_timeout(gen(), 5)]
        assert out == ["a", "b"]

    async def test_empty_generator_returns(self):
        async def gen():
            if False:
                yield "x"

        out = [item async for item in _async_generator_with_timeout(gen(), 5)]
        assert out == []

    async def test_timeout_stops_stream_gracefully(self):
        async def gen():
            yield "a"
            await asyncio.sleep(10)

        out = [item async for item in _async_generator_with_timeout(gen(), 0.05)]
        assert out == ["a"]


class TestMemoryContextToPromptText:
    def test_empty_context_returns_empty(self):
        assert MemoryContext().to_prompt_text() == ""

    def test_renders_sections_in_order(self):
        payload = ConversationSummaryPayload(
            summary="摘要",
            conversation_goal="目标",
            stable_facts=["f1", "f2"],
            user_preferences=["p1"],
            resolved_points=["r1"],
            pending_questions=["q1"],
            retrieval_hints=["h1"],
        )
        text = MemoryContext(summary_payload=payload).to_prompt_text()
        order = [text.index(t) for t in ("【长期会话摘要】", "【会话目标】", "【已确认事实】", "【用户偏好与约束】", "【已解决问题】", "【待跟进问题】", "【检索提示】")]
        assert order == sorted(order)
        assert "- f1" in text and "- f2" in text

    def test_skips_empty_sections(self):
        payload = ConversationSummaryPayload(summary="只有摘要")
        text = MemoryContext(summary_payload=payload).to_prompt_text()
        assert "【长期会话摘要】" in text
        assert "【检索提示】" not in text

    def test_bullet_format_per_line(self):
        payload = ConversationSummaryPayload(stable_facts=["a", "b"])
        text = MemoryContext(summary_payload=payload).to_prompt_text()
        assert "- a\n- b" in text


class TestCreateMemoryStrategy:
    def test_none_strategy(self, monkeypatch):
        monkeypatch.setattr("app.chat.memory.settings.memory.strategy", "none")
        assert isinstance(create_memory_strategy(), NoMemoryStrategy)

    def test_sliding_window_strategy(self, monkeypatch):
        monkeypatch.setattr("app.chat.memory.settings.memory.strategy", "sliding_window")
        assert isinstance(create_memory_strategy(), SlidingWindowStrategy)

    def test_summary_compression_strategy(self, monkeypatch):
        monkeypatch.setattr("app.chat.memory.settings.memory.strategy", "summary_compression")
        assert isinstance(create_memory_strategy(), SummaryCompressionStrategy)

    def test_unknown_strategy_falls_back_to_sliding_window(self, monkeypatch):
        monkeypatch.setattr("app.chat.memory.settings.memory.strategy", "unknown_mode")
        assert isinstance(create_memory_strategy(), SlidingWindowStrategy)

    def test_explicit_argument_overrides_settings(self, monkeypatch):
        monkeypatch.setattr("app.chat.memory.settings.memory.strategy", "summary_compression")
        assert isinstance(create_memory_strategy("none"), NoMemoryStrategy)
