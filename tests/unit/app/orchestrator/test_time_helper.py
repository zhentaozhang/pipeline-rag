from app.orchestrator.time_helper import TimeSensitiveQueryHelper as H


class TestIsTimeSensitive:
    def test_relative_ref(self):
        assert H.is_time_sensitive("今天天气怎么样") is True
        assert H.is_time_sensitive("明天有什么安排") is True

    def test_fresh_info(self):
        assert H.is_time_sensitive("北京天气") is True
        assert H.is_time_sensitive("最新新闻") is True

    def test_calendar(self):
        assert H.is_time_sensitive("今天是周几") is True

    def test_not_sensitive(self):
        assert H.is_time_sensitive("如何配置数据库") is False
        assert H.is_time_sensitive("") is False


class TestEnrich:
    def test_not_sensitive_unchanged(self):
        assert H.enrich("如何配置数据库") == "如何配置数据库"

    def test_sensitive_prefixed(self):
        out = H.enrich("今天天气")
        assert out.startswith("[当前时间：")
        assert out.endswith("] 今天天气")


class TestGetCurrentTimeContext:
    def test_format(self):
        out = H.get_current_time_context()
        assert "当前时间：" in out
        assert "年" in out and "月" in out and "日" in out


class TestRequiresCurrentDateAnchoring:
    def test_empty(self):
        assert H.requires_current_date_anchoring("") is False
        assert H.requires_current_date_anchoring("   ") is False

    def test_relative_time(self):
        assert H.requires_current_date_anchoring("今天的状态") is True

    def test_historical_intent_only(self):
        assert H.requires_current_date_anchoring("去年发生了什么") is False

    def test_calendar(self):
        assert H.requires_current_date_anchoring("今天是星期几") is True

    def test_current_info_domain(self):
        assert H.requires_current_date_anchoring("今天的天气") is True


class TestRequiresFreshSearch:
    def test_empty(self):
        assert H.requires_fresh_search("") is False

    def test_historical_excluded(self):
        assert H.requires_fresh_search("去年油价") is False

    def test_explicit_date_excluded(self):
        assert H.requires_fresh_search("2024-05-01的新闻") is False

    def test_calendar_excluded(self):
        assert H.requires_fresh_search("今天是几号") is False

    def test_current_domain(self):
        assert H.requires_fresh_search("上海天气") is True
        assert H.requires_fresh_search("今日油价") is True

    def test_current_keywords(self):
        assert H.requires_fresh_search("现在发生什么") is True
        assert H.requires_fresh_search("最新消息") is True

    def test_plain_question(self):
        assert H.requires_fresh_search("如何配置数据库") is False


class TestBuildEffectiveSearchQuery:
    def test_empty(self):
        assert H.build_effective_search_query("", "2026-08-08") == ""

    def test_no_current_date(self):
        assert H.build_effective_search_query(" 今天天气 ", "") == "今天天气"

    def test_not_requiring_anchoring(self):
        assert H.build_effective_search_query("如何配置", "2026-08-08") == "如何配置"

    def test_explicit_date_kept(self):
        assert H.build_effective_search_query("2024年5月1日发生了什么", "2026-08-08") == "2024年5月1日发生了什么"

    def test_date_already_in_query(self):
        q = "2026-08-08的新闻"
        assert H.build_effective_search_query(q, "2026-08-08") == q

    def test_historical_excluded(self):
        assert H.build_effective_search_query("去年业绩", "2026-08-08") == "去年业绩"

    def test_appends_hint(self):
        out = H.build_effective_search_query("明天的天气", "2026-08-08")
        assert out == "明天的天气 2026-08-08 明天"

    def test_derive_default_today(self):
        out = H.build_effective_search_query("当前进展", "2026-08-08")
        assert out.endswith("最新")
        assert "当前进展 2026-08-08" in out


class TestContainsExplicitDate:
    def test_patterns(self):
        assert H.contains_explicit_date("2024-05-01") is True
        assert H.contains_explicit_date("2024/05/01") is True
        assert H.contains_explicit_date("2024年5月1日") is True
        assert H.contains_explicit_date("5月1日") is True

    def test_no_match(self):
        assert H.contains_explicit_date("今天") is False
        assert H.contains_explicit_date("") is False


class TestHasRelativeTimeReference:
    def test_match(self):
        assert H.has_relative_time_reference("今天怎么样") is True
        assert H.has_relative_time_reference("无时间词") is False


class TestDeriveTemporalHint:
    def test_each_bucket(self):
        assert H.derive_temporal_hint("明天如何") == "明天"
        assert H.derive_temporal_hint("昨天如何") == "昨天"
        assert H.derive_temporal_hint("本周安排") == "本周"
        assert H.derive_temporal_hint("本月计划") == "本月"
        assert H.derive_temporal_hint("今年目标") == "今年"
        assert H.derive_temporal_hint("现在情况") == "最新"
        assert H.derive_temporal_hint("普通问题") == "今天"
