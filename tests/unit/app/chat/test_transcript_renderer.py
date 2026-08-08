
from app.chat.support import (
    StreamEventMetadata,
    is_dashscope_provider,
    resolve_provider,
)
from app.chat.transcript_renderer import (
    MAX_ANSWER_LENGTH,
    HistoryTurn,
    TranscriptRenderer,
    clip_recent_transcript,
    clip_text,
)


class TestClipText:
    def test_short_unchanged(self):
        assert clip_text("你好", 10) == "你好"

    def test_long_clipped_with_ellipsis(self):
        out = clip_text("x" * 20, 10)
        assert len(out) == 10
        assert out.endswith("…")

    def test_empty(self):
        assert clip_text("", 10) == ""
        assert clip_text("  ", 10) == ""

    def test_zero_max(self):
        assert clip_text("abc", 1) == "…"


class TestClipRecentTranscript:
    def test_short_unchanged(self):
        assert clip_recent_transcript("abc", 10) == "abc"

    def test_long_keeps_tail(self):
        out = clip_recent_transcript("x" * 20, 10)
        assert len(out) == 10
        assert out.startswith("…")
        assert out.endswith("x")


class TestRenderRecentTranscript:
    def test_empty_turns(self):
        assert TranscriptRenderer.render_recent_transcript([]) == ""

    def test_renders_question_and_answer(self, monkeypatch):
        monkeypatch.setattr(
            "app.chat.transcript_renderer.settings",
            type("S", (), {"memory": type("M", (), {"max_window_chars": 0})()})(),
        )
        turns = [HistoryTurn("问题一", "回答一")]
        out = TranscriptRenderer.render_recent_transcript(turns)
        assert "【最近对话原文】" in out
        assert "用户：问题一" in out
        assert "助手：回答一" in out

    def test_skips_missing_fields(self, monkeypatch):
        monkeypatch.setattr(
            "app.chat.transcript_renderer.settings",
            type("S", (), {"memory": type("M", (), {"max_window_chars": 0})()})(),
        )
        out = TranscriptRenderer.render_recent_transcript([HistoryTurn("", "")])
        assert "【最近对话原文】" in out


class TestRenderAnswerRecentTranscript:
    def test_question_only(self, monkeypatch):
        monkeypatch.setattr(
            "app.chat.transcript_renderer.settings",
            type("S", (), {"rag": type("R", (), {"answer_history_max_chars": 0})()})(),
        )
        turns = [HistoryTurn("问题一", "回答一")]
        out = TranscriptRenderer.render_answer_recent_transcript(turns)
        assert "【最近相关对话】" in out
        assert "用户：问题一" in out
        assert "助手" not in out


class TestRenderCompressionTranscript:
    def test_renders_exchanges(self):
        batch = [
            type("E", (), {"question": "q1", "answer": "a1"})(),
            type("E", (), {"question": "", "answer": "a2"})(),
        ]
        out = TranscriptRenderer.render_compression_transcript(batch)
        assert "用户：q1" in out
        assert "助手：a1" in out
        assert "助手：a2" in out


class TestAssembleHistory:
    def test_joins_non_blank(self):
        out = TranscriptRenderer.assemble_history("长期总结", "最近对话")
        assert out == "长期总结\n\n最近对话"

    def test_single_part(self):
        assert TranscriptRenderer.assemble_history("", "最近") == "最近"
        assert TranscriptRenderer.assemble_history("  ", "") == ""


class TestConstants:
    def test_lengths(self):
        assert MAX_ANSWER_LENGTH == 320


class TestSupport:
    def test_resolve_provider(self):
        assert resolve_provider("") == "unknown"
        assert resolve_provider(None) == "unknown"
        assert resolve_provider("https://api.siliconflow.cn") == "siliconflow"
        assert resolve_provider("https://dashscope.aliyuncs.com") == "dashscope"
        assert resolve_provider("https://api.openai.com") == "https://api.openai.com"

    def test_is_dashscope(self):
        assert is_dashscope_provider("dashscope") is True
        assert is_dashscope_provider("openai") is False

    def test_metadata_defaults(self):
        m = StreamEventMetadata()
        assert m.conversation_id == ""
        assert m.exchange_id is None
