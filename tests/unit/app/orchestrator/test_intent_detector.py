from app.common.enums import ChatQueryMode
from app.orchestrator.intent_detector import (
    build_document_mode_no_evidence_reply,
    build_open_chat_suggestion,
    looks_like_capability_question,
    looks_like_open_chat_question,
    normalize_chat_mode,
)


class TestNormalizeChatMode:
    def test_known_modes(self):
        assert normalize_chat_mode("auto") == ChatQueryMode.AUTO_DOCUMENT
        assert normalize_chat_mode("document") == ChatQueryMode.DOCUMENT
        assert normalize_chat_mode("open_chat") == ChatQueryMode.OPEN_CHAT

    def test_unknown_falls_back_to_auto(self):
        assert normalize_chat_mode("weird") == ChatQueryMode.AUTO_DOCUMENT
        assert normalize_chat_mode("") == ChatQueryMode.AUTO_DOCUMENT


class TestLooksLikeCapabilityQuestion:
    def test_hits(self):
        assert looks_like_capability_question("你都能干什么") is True
        assert looks_like_capability_question("你是谁") is True
        assert looks_like_capability_question("告诉我你能做什么") is True

    def test_miss(self):
        assert looks_like_capability_question("如何配置数据库") is False
        assert looks_like_capability_question("") is False
        assert looks_like_capability_question(None) is False


class TestLooksLikeOpenChatQuestion:
    def test_fresh_search_always_true(self):
        assert looks_like_open_chat_question("普通问题", True) is True

    def test_open_hint(self):
        assert looks_like_open_chat_question("今天天气", False) is True

    def test_chitchat_hint(self):
        assert looks_like_open_chat_question("你好", False) is True

    def test_normal_question(self):
        assert looks_like_open_chat_question("如何配置数据库", False) is False

    def test_empty(self):
        assert looks_like_open_chat_question("", False) is False
        assert looks_like_open_chat_question(None, False) is False


class TestTimeLimiterDoesNotHijackRouting:
    """回归（审查报告 D1）：时间限定词不得触发改道联网。

    早前 `_OPEN_CHAT_HINTS` 把「今天 / 明天 / 最新 / 现在」与「天气 / 股价 / 汇率」
    混在同一张领域词表里，导致 AUTO_DOCUMENT 模式下含这些词的知识库问题被静默
    改道到联网搜索，完全绕过知识库。
    """

    def test_time_limiter_alone_stays_in_knowledge_base(self):
        assert looks_like_open_chat_question("今天报销流程有变化吗", False) is False
        assert looks_like_open_chat_question("明天的会议安排是什么", False) is False

    def test_real_time_domain_still_routes(self):
        assert looks_like_open_chat_question("今天天气怎么样", False) is True
        assert looks_like_open_chat_question("最新的汇率是多少", False) is True
        assert looks_like_open_chat_question("台风预警", False) is True

    def test_domain_list_single_source_of_truth(self):
        """领域词表唯一来源是 TimeSensitiveQueryHelper，不再各自维护一份。"""
        from app.orchestrator.time_helper import TimeSensitiveQueryHelper

        for q in ("上海天气", "今日油价", "最新新闻"):
            assert TimeSensitiveQueryHelper.is_fresh_info_domain(q) is True
        for q in ("今天报销流程有变化吗", "如何配置数据库"):
            assert TimeSensitiveQueryHelper.is_fresh_info_domain(q) is False


class TestBuildOpenChatSuggestion:
    def test_copy_decoupled_from_routing(self):
        text = build_open_chat_suggestion()
        assert "当前文档问答" in text
        assert "开放式提问" in text


class TestBuildDocumentModeNoEvidenceReply:
    def test_capability_reply(self):
        reply = build_document_mode_no_evidence_reply("你都能干什么", False)
        assert "当前文档问答" in reply
        assert "开放式提问" in reply

    def test_open_chat_reply(self):
        reply = build_document_mode_no_evidence_reply("今天天气", False)
        assert "当前文档问答" in reply
        assert "开放式提问" in reply

    def test_normal_reply(self, monkeypatch):
        import app.orchestrator.intent_detector as idm

        monkeypatch.setattr(
            idm,
            "get_settings",
            lambda: __import__("types").SimpleNamespace(
                rag=__import__("types").SimpleNamespace(no_evidence_reply="自定义无证据回复")
            ),
        )
        assert build_document_mode_no_evidence_reply("如何配置", False) == "自定义无证据回复"
