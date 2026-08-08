"""query_rewriter 纯逻辑测试：多问题检测、改写判断、规则拆分、JSON 解析与结果调解（无 LLM）。"""


from app.orchestrator.query_rewriter import (
    ChatQueryRewriteService,
    _clip_tail,
    _extract_recent_user_questions,
    _looks_like_explicit_multi_question,
    _looks_like_follow_up_question,
    _needs_rewrite,
    _rule_based_split,
)

svc = ChatQueryRewriteService()


class TestLooksLikeExplicitMultiQuestion:
    def test_empty_false(self):
        assert _looks_like_explicit_multi_question("") is False
        assert _looks_like_explicit_multi_question(None) is False

    def test_two_question_marks(self):
        assert _looks_like_explicit_multi_question("什么是 RAG？什么是向量？") is True

    def test_one_question_mark_not_multi(self):
        assert _looks_like_explicit_multi_question("什么是 RAG？") is False

    def test_semicolon_delimiters(self):
        assert _looks_like_explicit_multi_question("RAG 是什么；怎么配置") is True

    def test_multiple_lines(self):
        assert _looks_like_explicit_multi_question("第一问\n第二问") is True

    def test_numbered_pattern(self):
        assert _looks_like_explicit_multi_question("1. RAG 原理 2. 部署") is True
        assert _looks_like_explicit_multi_question("第一步怎么做") is False

    def test_explicit_fenbie(self):
        assert _looks_like_explicit_multi_question("分别说明 RAG 和 Agent 的区别") is True


class TestNeedsRewrite:
    def test_short_question_without_history(self):
        assert _needs_rewrite("太短", "") is True

    def test_long_question_without_history_not_rewritten(self):
        assert _needs_rewrite("这个问题已经足够长了", "") is False

    def test_multi_question_always_rewritten(self):
        assert _needs_rewrite("什么是 RAG？什么是 Agent？", "") is True

    def test_with_history_raises_threshold(self):
        assert _needs_rewrite("有历史时中等长度问题", "有历史") is True
        assert _needs_rewrite("这个问题足够长所以不需要对它进行改写处理", "有历史") is False


class TestRuleBasedSplit:
    def test_splits_on_question_marks(self):
        result = _rule_based_split("什么是 RAG？什么是 Agent？")
        assert result == ["什么是 RAG", "什么是 Agent"]

    def test_dedup_keeps_order(self):
        result = _rule_based_split("问什么？问什么？问别的")
        assert result == ["问什么", "问别的"]

    def test_respects_max_count(self):
        result = _rule_based_split("a？b？c？d？e？", max_count=3)
        assert len(result) == 3

    def test_no_delimiters_returns_single(self):
        assert _rule_based_split("普通问题") == ["普通问题"]

    def test_blank_returns_original(self):
        assert _rule_based_split("") == [""]


class TestLooksLikeFollowUpQuestion:
    def test_hint_words(self):
        assert _looks_like_follow_up_question("刚才说的那个是什么", True) is True

    def test_ordinal_pattern(self):
        assert _looks_like_follow_up_question("第三条怎么理解", True) is True

    def test_short_question_with_context(self):
        assert _looks_like_follow_up_question("然后呢", True) is True

    def test_ne_ma_suffix_within_18(self):
        assert _looks_like_follow_up_question("它支持向量检索吗", True) is True

    def test_long_question_not_follow_up(self):
        assert _looks_like_follow_up_question("关于向量数据库的索引构建与检索优化配置说明", True) is False

    def test_without_context_never_follow_up(self):
        assert _looks_like_follow_up_question("刚才说的", False) is False


class TestExtractRecentUserQuestions:
    def test_extracts_user_lines(self):
        text = "【最近相关对话】\n用户：问题一\n助手：回答一\n用户：问题二"
        assert _extract_recent_user_questions(text) == "用户：问题一\n用户：问题二"

    def test_strips_header_variants(self):
        assert _extract_recent_user_questions("最近相关对话：\n用户：q") == "用户：q"
        assert _extract_recent_user_questions("用户：q") == "用户：q"

    def test_empty(self):
        assert _extract_recent_user_questions("") == ""
        assert _extract_recent_user_questions("助手：only") == ""


class TestClipTail:
    def test_short_unchanged(self):
        assert _clip_tail("abc", 10) == "abc"

    def test_long_ellipsis_prefix(self):
        assert _clip_tail("x" * 10, 4) == "…xxx"

    def test_max_chars_one_empty(self):
        assert _clip_tail("abc", 1) == ""


class TestParse:
    def test_valid_json(self):
        parsed = svc._parse('{"rewrite": "RAG 是什么", "should_split": false, "keywords": ["RAG"]}')
        assert parsed["rewrite"] == "RAG 是什么"
        assert parsed["should_split"] is False
        assert parsed["keywords"] == ["RAG"]

    def test_missing_rewrite_returns_none(self):
        assert svc._parse("{}") is None
        assert svc._parse('{"rewrite": "  "}') is None

    def test_invalid_json_returns_none(self):
        assert svc._parse("not json") is None

    def test_filters_blank_sub_questions(self):
        parsed = svc._parse('{"rewrite": "r", "sub_questions": ["a", "", "  ", "b"]}')
        assert parsed["sub_questions"] == ["a", "b"]

    def test_empty_raw_returns_none(self):
        assert svc._parse("") is None
        assert svc._parse(None) is None


class TestNormalizeRewriteResult:
    def test_none_parsed_returns_none(self):
        assert svc._normalize_rewrite_result("q", None) is None

    def test_no_split_single_sub_question(self):
        parsed = {"rewrite": "重写后", "should_split": False, "sub_questions": ["重写后"], "keywords": []}
        result = svc._normalize_rewrite_result("原问题", parsed)
        assert result.rewritten == "重写后"
        assert result.sub_questions == ["重写后"]

    def test_should_split_none_falls_back_to_explicit_multi(self):
        parsed = {"rewrite": "重写后", "should_split": None, "sub_questions": [], "keywords": []}
        result = svc._normalize_rewrite_result("什么是 RAG？什么是 Agent？", parsed)
        assert result.sub_questions == ["重写后"]

    def test_rule_based_fallback_when_no_sub_questions(self, monkeypatch):
        monkeypatch.setattr("app.orchestrator.query_rewriter.settings.rag.max_sub_questions", 4)
        parsed = {"rewrite": "重写", "should_split": False, "sub_questions": [], "keywords": []}
        result = svc._normalize_rewrite_result("a？b？c", parsed)
        assert result.sub_questions == ["a", "b", "c"]

    def test_single_sub_question_converges_to_rewrite(self):
        parsed = {"rewrite": "最终", "should_split": False, "sub_questions": ["旧的"], "keywords": []}
        result = svc._normalize_rewrite_result("原问题", parsed)
        assert result.sub_questions == ["最终"]

    def test_truncates_over_max_sub(self, monkeypatch):
        monkeypatch.setattr("app.orchestrator.query_rewriter.settings.rag.max_sub_questions", 2)
        parsed = {"rewrite": "r", "should_split": True, "sub_questions": ["1", "2", "3"], "keywords": []}
        result = svc._normalize_rewrite_result("a？b？c？d", parsed)
        assert len(result.sub_questions) == 2
