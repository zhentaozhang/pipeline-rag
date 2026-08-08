"""common 工具层测试：text_utils 文本处理、utils.safe_int、sse 事件格式化（零依赖）。"""

import json
from datetime import UTC, datetime

from app.common.sse import SSEEventType, sse_event
from app.common.text_utils import (
    clip_head,
    clip_tail,
    first_non_blank,
    join_non_blank,
    normalize_step_numeral,
    normalize_text,
    safe_text,
)
from app.common.utils import safe_int


class TestNormalizeStepNumeral:
    def test_cn_numeral_to_arabic(self):
        assert normalize_step_numeral("第一步") == "第1步"
        assert normalize_step_numeral("第三步") == "第3步"
        assert normalize_step_numeral("第十步") == "第10步"

    def test_handles_suffix_variants(self):
        assert normalize_step_numeral("第二个步骤") == "第2个步骤"
        assert normalize_step_numeral("第四条") == "第4条"

    def test_non_step_context_unchanged(self):
        assert normalize_step_numeral("一马当先") == "一马当先"

    def test_unsupported_numeral_unchanged(self):
        assert normalize_step_numeral("第一百步") == "第一百步"


class TestNormalizeText:
    def test_strips_whitespace_and_punctuation(self):
        assert normalize_text("  你好，世界！ ") == "你好世界"
        assert normalize_text("真的吗？") == "真的吗"

    def test_lowercases_english(self):
        assert normalize_text("Hello World") == "helloworld"

    def test_empty_returns_empty(self):
        assert normalize_text("") == ""
        assert normalize_text("   ") == ""
        assert normalize_text(None) == ""


class TestFirstNonBlank:
    def test_uses_primary_when_present(self):
        assert first_non_blank(" 主要 ", "fallback") == "主要"

    def test_falls_back_when_primary_blank(self):
        assert first_non_blank("", "fallback") == "fallback"
        assert first_non_blank(None, "fallback") == "fallback"
        assert first_non_blank("   ", "fallback") == "fallback"


class TestSafeText:
    def test_none_becomes_empty(self):
        assert safe_text(None) == ""

    def test_strips(self):
        assert safe_text("  x  ") == "x"


class TestClipHead:
    def test_short_unchanged(self):
        assert clip_head("hello", 10) == "hello"

    def test_long_ellipsis_at_end(self):
        assert clip_head("x" * 10, 4) == "xxx…"

    def test_max_chars_one_returns_empty(self):
        assert clip_head("abc", 1) == ""


class TestClipTail:
    def test_short_unchanged(self):
        assert clip_tail("hello", 10) == "hello"

    def test_long_ellipsis_at_start(self):
        assert clip_tail("x" * 10, 4) == "…xxx"

    def test_max_chars_one_returns_empty(self):
        assert clip_tail("abc", 1) == ""


class TestJoinNonBlank:
    def test_both_present_joined_with_double_newline(self):
        assert join_non_blank("a", "b") == "a\n\nb"

    def test_left_blank_returns_right(self):
        assert join_non_blank("", "b") == "b"

    def test_right_blank_returns_left(self):
        assert join_non_blank("a", None) == "a"

    def test_both_blank_returns_empty(self):
        assert join_non_blank(None, "  ") == ""


class TestSafeInt:
    def test_valid_int(self):
        assert safe_int("42") == 42

    def test_invalid_returns_default(self):
        assert safe_int("abc") == 0
        assert safe_int(None) == 0

    def test_custom_default(self):
        assert safe_int("abc", default=-1) == -1

    def test_float_string_returns_default(self):
        assert safe_int("3.14") == 0


class TestSseEvent:
    def test_basic_format_with_terminator(self):
        raw = sse_event(SSEEventType.TEXT, "hi", _now=datetime(2026, 8, 7, 12, 0, tzinfo=UTC))
        assert raw.startswith("data: ")
        assert raw.endswith("\n\n")
        payload = json.loads(raw[len("data: ") :].strip())
        assert payload["type"] == "text"
        assert payload["content"] == "hi"

    def test_timestamp_utc_z_suffix(self):
        raw = sse_event(SSEEventType.TEXT, "x", _now=datetime(2026, 8, 7, 12, 0, tzinfo=UTC))
        payload = json.loads(raw[len("data: ") :].strip())
        assert payload["timestamp"] == "2026-08-07T12:00:00Z"

    def test_list_content_adds_count_for_reference(self):
        raw = sse_event(SSEEventType.REFERENCE, [{"id": 1}, {"id": 2}])
        payload = json.loads(raw[len("data: ") :].strip())
        assert payload["count"] == 2

    def test_list_content_no_count_for_text(self):
        raw = sse_event(SSEEventType.TEXT, ["a", "b"])
        payload = json.loads(raw[len("data: ") :].strip())
        assert "count" not in payload

    def test_conversation_id_included_when_present(self):
        raw = sse_event(SSEEventType.TEXT, "x", conversation_id="c1")
        assert '"conversationId": "c1"' in raw

    def test_blank_conversation_id_omitted(self):
        raw = sse_event(SSEEventType.TEXT, "x", conversation_id="  ")
        assert "conversationId" not in raw

    def test_exchange_id_omitted_when_zero_or_negative(self):
        assert "exchangeId" not in sse_event(SSEEventType.TEXT, "x", exchange_id=0)
        assert "exchangeId" not in sse_event(SSEEventType.TEXT, "x", exchange_id=-3)

    def test_exchange_id_included_when_positive(self):
        raw = sse_event(SSEEventType.TEXT, "x", exchange_id=7)
        assert '"exchangeId": 7' in raw

    def test_chinese_content_unescaped(self):
        raw = sse_event(SSEEventType.TEXT, "中文内容")
        assert "中文内容" in raw
        assert "\\u" not in raw

    def test_done_event(self):
        raw = sse_event(SSEEventType.DONE)
        payload = json.loads(raw[len("data: ") :].strip())
        assert payload["type"] == "done"
        assert payload["content"] is None
