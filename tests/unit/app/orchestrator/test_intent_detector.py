from app.common.enums import ChatQueryMode
from app.orchestrator.intent_detector import (
    build_document_mode_no_evidence_reply,
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
