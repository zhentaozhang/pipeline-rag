"""ConversationMemoryCompressor 纯逻辑测试：fallback 合并、payload 规范化、长摘要渲染（无 DB/LLM）。"""

from types import SimpleNamespace

import pytest

from app.chat.memory import ConversationSummaryPayload
from app.chat.memory_compressor import ConversationMemoryCompressor


def _exchange(question: str, answer: str = "", eid: int = 0) -> SimpleNamespace:
    return SimpleNamespace(question=question, answer=answer, id=eid)


@pytest.fixture
def compressor() -> ConversationMemoryCompressor:
    return ConversationMemoryCompressor()


class TestFallbackMerge:
    def test_empty_batch_keeps_payload(self, compressor):
        payload = ConversationSummaryPayload(summary="已有摘要")
        merged = compressor._fallback_merge(payload, [])
        assert merged.summary == "已有摘要"
        assert merged.pending_questions == []

    def test_appends_highlights_to_summary(self, compressor):
        payload = ConversationSummaryPayload(summary="")
        merged = compressor._fallback_merge(payload, [_exchange("问题A", "结论A")])
        assert "用户关注：问题A" in merged.summary
        assert "已有结论：结论A" in merged.summary

    def test_limits_highlights_to_four(self, compressor):
        batch = [_exchange(f"q{i}", f"a{i}") for i in range(6)]
        merged = compressor._fallback_merge(ConversationSummaryPayload(), batch)
        assert merged.summary.count("用户关注：") <= 4

    def test_sets_conversation_goal_from_last_question_when_empty(self, compressor):
        merged = compressor._fallback_merge(
            ConversationSummaryPayload(), [_exchange("q1"), _exchange("目标问题")]
        )
        assert merged.conversation_goal == "目标问题"

    def test_keeps_existing_conversation_goal(self, compressor):
        payload = ConversationSummaryPayload(conversation_goal="原有目标")
        merged = compressor._fallback_merge(payload, [_exchange("新问题")])
        assert merged.conversation_goal == "原有目标"

    def test_appends_pending_questions_deduplicated(self, compressor):
        payload = ConversationSummaryPayload(pending_questions=["已有"])
        merged = compressor._fallback_merge(
            payload, [_exchange("q1"), _exchange("已有")]
        )
        assert merged.pending_questions == ["已有", "q1"]

    def test_extracts_retrieval_hints_from_last_question(self, compressor):
        merged = compressor._fallback_merge(
            ConversationSummaryPayload(), [_exchange("RAG chunk_size 如何设置")]
        )
        assert merged.retrieval_hints

    def test_clips_summary_to_max_summary_chars(self, compressor, monkeypatch):
        monkeypatch.setattr("app.chat.memory_compressor.settings.memory.max_summary_chars", 50)
        merged = compressor._fallback_merge(
            ConversationSummaryPayload(),
            [_exchange("长" * 100, "长" * 100)],
        )
        assert len(merged.summary) <= 50


class TestNormalizePayload:
    def test_clips_summary_to_max(self, compressor, monkeypatch):
        monkeypatch.setattr("app.chat.memory_compressor.settings.memory.max_summary_chars", 20)
        normalized = compressor._normalize_payload(ConversationSummaryPayload(summary="x" * 100))
        assert len(normalized.summary) <= 20

    def test_synthesizes_summary_when_empty(self, compressor):
        normalized = compressor._normalize_payload(
            ConversationSummaryPayload(
                conversation_goal="目标", stable_facts=["事实1"], pending_questions=["待办"]
            )
        )
        assert "目标：目标" in normalized.summary
        assert "事实：事实1" in normalized.summary

    def test_empty_payload_keeps_empty_summary(self, compressor):
        normalized = compressor._normalize_payload(ConversationSummaryPayload())
        assert normalized.summary == ""

    def test_dedupes_and_limits_sections(self, compressor):
        normalized = compressor._normalize_payload(
            ConversationSummaryPayload(stable_facts=["a", "a", "b", ""])
        )
        assert normalized.stable_facts == ["a", "b"]


class TestSynthesizeSummaryFromSections:
    def test_empty_payload_returns_empty(self, compressor):
        assert compressor._synthesize_summary_from_sections(ConversationSummaryPayload()) == ""

    def test_joins_goal_facts_pending(self, compressor):
        text = compressor._synthesize_summary_from_sections(
            ConversationSummaryPayload(
                conversation_goal="目标", stable_facts=["事实"], pending_questions=["待办"]
            )
        )
        assert "目标：目标" in text
        assert "事实：事实" in text
        assert "待跟进：待办" in text


class TestBuildLongTermSummaryText:
    def test_renders_all_section_titles(self, compressor):
        text = compressor._build_long_term_summary_text(
            ConversationSummaryPayload(
                summary="摘要",
                conversation_goal="目标",
                stable_facts=["f1"],
                user_preferences=["p1"],
                resolved_points=["r1"],
                pending_questions=["q1"],
                retrieval_hints=["h1"],
            )
        )
        for title in ("长期会话摘要", "会话目标", "已确认事实", "用户偏好与约束", "已解决问题", "待跟进问题", "检索提示"):
            assert f"【{title}】" in text
        assert "- f1" in text

    def test_empty_payload_returns_empty(self, compressor):
        assert compressor._build_long_term_summary_text(ConversationSummaryPayload()) == ""

    def test_skips_empty_sections(self, compressor):
        text = compressor._build_long_term_summary_text(
            ConversationSummaryPayload(summary="只有摘要")
        )
        assert "【长期会话摘要】" in text
        assert "【会话目标】" not in text
