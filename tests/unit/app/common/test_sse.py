from datetime import UTC, datetime

from app.common.sse import SSEEventType, sse_event


class TestSSEEvent:
    def test_basic_shape(self):
        out = sse_event(SSEEventType.TEXT, "你好", _now=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC))
        assert out == (
            'data: {"type": "text", "content": "你好", "timestamp": '
            '"2026-01-01T12:00:00Z"}\n\n'
        )

    def test_none_content(self):
        out = sse_event(SSEEventType.DONE, _now=datetime(2026, 1, 1, tzinfo=UTC))
        assert '"content": null' in out

    def test_reference_adds_count(self):
        out = sse_event(
            SSEEventType.REFERENCE,
            [{"id": 1}, {"id": 2}],
            _now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert '"count": 2' in out

    def test_text_list_no_count(self):
        out = sse_event(SSEEventType.TEXT, ["a", "b"], _now=datetime(2026, 1, 1, tzinfo=UTC))
        assert '"count"' not in out

    def test_conversation_and_exchange(self):
        out = sse_event(
            SSEEventType.STATUS,
            "ok",
            conversation_id="c1",
            exchange_id=3,
            _now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert '"conversationId": "c1"' in out
        assert '"exchangeId": 3' in out

    def test_blank_conversation_omitted(self):
        out = sse_event(
            SSEEventType.STATUS,
            "ok",
            conversation_id="  ",
            exchange_id=0,
            _now=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert "conversationId" not in out
        assert "exchangeId" not in out

    def test_unicode_kept(self):
        out = sse_event(SSEEventType.TEXT, "中文内容", _now=datetime(2026, 1, 1, tzinfo=UTC))
        assert "中文内容" in out
        assert "\\u" not in out

    def test_alias_message(self):
        assert SSEEventType.MESSAGE == SSEEventType.TEXT
