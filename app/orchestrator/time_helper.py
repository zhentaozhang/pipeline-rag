"""
时间感知查询助手

功能：当问题中包含时间相关词（"今天"、"现在"、"当前"等），
自动在问题前注入当前时间上下文，帮助 LLM 理解时间语义。
"""

import re
from datetime import UTC, datetime

_RELATIVE_TIME_REFS = [
    "今天",
    "今日",
    "明天",
    "明日",
    "昨天",
    "昨日",
    "后天",
    "前天",
    "现在",
    "当前",
    "目前",
    "此刻",
    "实时",
    "最新",
    "刚刚",
    "本周",
    "这周",
    "本月",
    "这个月",
    "今年",
    "本年度",
    "本季度",
    "周几",
    "星期几",
    "几号",
    "日期",
    "几月几号",
]

_FRESH_INFO_KEYWORDS = [
    "天气",
    "气温",
    "温度",
    "降雨",
    "下雨",
    "下雪",
    "空气质量",
    "aqi",
    "限号",
    "限行",
    "尾号限行",
    "汇率",
    "金价",
    "黄金价格",
    "银价",
    "油价",
    "股价",
    "行情",
    "大盘",
    "指数",
    "新闻",
    "头条",
    "热搜",
    "热榜",
    "路况",
    "拥堵",
    "票房",
    "排片",
    "航班",
    "班次",
    "列车",
    "高铁",
    "火车",
    "地铁运营",
    "比分",
    "赛果",
    "赛程",
    "比赛结果",
    "预警",
    "台风",
]

_CALENDAR_KEYWORDS = ["周几", "星期几", "几号", "日期", "几月几号", "星期", "周"]

_HISTORICAL_KEYWORDS = [
    "历史",
    "过去",
    "去年",
    "前年",
    "上周",
    "上个月",
    "上月",
    "上一周",
    "上一月",
    "往年",
    "历年",
    "当时",
    "之前",
    "回顾",
    "曾经",
]


_EXPLICIT_DATE_PATTERN = re.compile(r"(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)|(\d{1,2}月\d{1,2}日)")


class TimeSensitiveQueryHelper:
    """
    时间感知查询预处理：检测时间敏感问题并注入当前时间上下文。
    """

    @staticmethod
    def is_time_sensitive(question: str) -> bool:
        q = question.lower()
        return (
            any(kw in q for kw in _RELATIVE_TIME_REFS)
            or any(kw in q for kw in _FRESH_INFO_KEYWORDS)
            or any(kw in q for kw in _CALENDAR_KEYWORDS)
        )

    @staticmethod
    def enrich(question: str) -> str:
        if not TimeSensitiveQueryHelper.is_time_sensitive(question):
            return question
        now = datetime.now(UTC).astimezone()
        time_str = now.strftime("%Y-%m-%d %H:%M %Z")
        return f"[当前时间：{time_str}] {question}"

    @staticmethod
    def get_current_time_context() -> str:
        now = datetime.now(UTC).astimezone()
        return f"当前时间：{now.strftime('%Y年%m月%d日 %H:%M')} ({now.strftime('%A')})"

    @staticmethod
    def requires_current_date_anchoring(query: str) -> bool:
        if not query or not query.strip():
            return False
        if (
            TimeSensitiveQueryHelper._has_historical_intent(query)
            and not TimeSensitiveQueryHelper._has_relative_time_reference(query)
            and not TimeSensitiveQueryHelper._looks_calendar_question(query)
        ):
            return False
        return (
            TimeSensitiveQueryHelper._has_relative_time_reference(query)
            or TimeSensitiveQueryHelper._looks_current_info_domain(query)
            or TimeSensitiveQueryHelper._looks_calendar_question(query)
        )

    @staticmethod
    def requires_fresh_search(query: str) -> bool:
        if not query or not query.strip():
            return False
        if TimeSensitiveQueryHelper._has_historical_intent(
            query
        ) or TimeSensitiveQueryHelper._contains_explicit_date(query):
            return False
        if TimeSensitiveQueryHelper._looks_calendar_question(query):
            return False
        normalized = TimeSensitiveQueryHelper._normalize(query)
        return TimeSensitiveQueryHelper._looks_current_info_domain(
            normalized
        ) or TimeSensitiveQueryHelper._contains_any(
            normalized, ["最新", "实时", "当前", "现在", "目前", "刚刚"]
        )

    @staticmethod
    def build_effective_search_query(query: str, current_date: str) -> str:
        if not query or not query.strip():
            return query
        trimmed_query = query.strip()
        if not current_date or not current_date.strip():
            return trimmed_query
        if not TimeSensitiveQueryHelper.requires_current_date_anchoring(trimmed_query):
            return trimmed_query
        if (
            TimeSensitiveQueryHelper._contains_explicit_date(trimmed_query)
            or (current_date and current_date in trimmed_query)
            or TimeSensitiveQueryHelper._has_historical_intent(trimmed_query)
        ):
            return trimmed_query
        return f"{trimmed_query} {current_date} {TimeSensitiveQueryHelper.derive_temporal_hint(trimmed_query)}"

    @staticmethod
    def contains_explicit_date(query: str) -> bool:
        return bool(query and query.strip() and _EXPLICIT_DATE_PATTERN.search(query))

    @staticmethod
    def has_relative_time_reference(query: str) -> bool:
        return TimeSensitiveQueryHelper._contains_any(
            TimeSensitiveQueryHelper._normalize(query), _RELATIVE_TIME_REFS
        )




    @staticmethod
    def derive_temporal_hint(query: str) -> str:
        normalized = TimeSensitiveQueryHelper._normalize(query)
        if TimeSensitiveQueryHelper._contains_any(normalized, ["明天", "明日"]):
            return "明天"
        if TimeSensitiveQueryHelper._contains_any(normalized, ["昨天", "昨日", "前天"]):
            return "昨天"
        if TimeSensitiveQueryHelper._contains_any(normalized, ["本周", "这周"]):
            return "本周"
        if TimeSensitiveQueryHelper._contains_any(normalized, ["本月", "这个月"]):
            return "本月"
        if TimeSensitiveQueryHelper._contains_any(normalized, ["今年", "本年度", "本季度"]):
            return "今年"
        if TimeSensitiveQueryHelper._contains_any(
            normalized, ["最新", "实时", "当前", "现在", "目前", "刚刚"]
        ):
            return "最新"
        return "今天"

    @staticmethod
    def _normalize(query: str) -> str:
        return query.strip().lower() if query and query.strip() else ""

    @staticmethod
    def _contains_any(query: str, candidates: list[str]) -> bool:
        if not query or not query.strip():
            return False
        return any(candidate in query for candidate in candidates)

    @staticmethod
    def _has_historical_intent(query: str) -> bool:
        return TimeSensitiveQueryHelper._contains_any(
            TimeSensitiveQueryHelper._normalize(query), _HISTORICAL_KEYWORDS
        )

    @staticmethod
    def _has_relative_time_reference(query: str) -> bool:
        return TimeSensitiveQueryHelper._contains_any(
            TimeSensitiveQueryHelper._normalize(query), _RELATIVE_TIME_REFS
        )

    @staticmethod
    def _looks_calendar_question(query: str) -> bool:
        return TimeSensitiveQueryHelper._contains_any(
            TimeSensitiveQueryHelper._normalize(query), _CALENDAR_KEYWORDS
        )

    @staticmethod
    def _looks_current_info_domain(query: str) -> bool:
        return TimeSensitiveQueryHelper._contains_any(
            TimeSensitiveQueryHelper._normalize(query), _FRESH_INFO_KEYWORDS
        )

    @staticmethod
    def _contains_explicit_date(query: str) -> bool:
        return bool(query and query.strip() and _EXPLICIT_DATE_PATTERN.search(query))
