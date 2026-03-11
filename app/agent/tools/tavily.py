"""
Tavily 联网搜索工具（供 LangGraph Agent 使用）

特性：
- API Key Bearer 认证头（非 JSON body）
- 时间锚定：关键字检测 + temporal hint 追加
- topic 校验：仅允许 general/news/finance，自动回退
- search_depth / include_raw_content 透传
- 指数退避重试（最多 2 次，200ms → 1200ms + 随机抖动）
- 异常兜底（不让工具失败影响 Agent 主流程）
"""

import asyncio
import random
import threading
from datetime import date
from typing import Any

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

_tavily_client: httpx.AsyncClient | None = None
_tavily_client_lock = threading.Lock()


def _get_tavily_client() -> httpx.AsyncClient:
    """模块级单例 httpx 客户端（避免每次重试创建新连接池）"""
    global _tavily_client
    if _tavily_client is None:
        with _tavily_client_lock:
            if _tavily_client is None:
                s = settings.tavily
                _tavily_client = httpx.AsyncClient(
                    timeout=(s.connect_timeout_ms / 1000, s.read_timeout_ms / 1000)
                )
    return _tavily_client


TAVILY_SETTINGS = settings.tavily

ALLOWED_TOPICS = {"general", "news", "finance"}

# ── 时间锚定 ─────────────────────────────────────────────────────────────────

RELATIVE_TIME_KEYWORDS = [
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

FRESH_INFORMATION_KEYWORDS = [
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

CALENDAR_KEYWORDS = [
    "周几",
    "星期几",
    "几号",
    "日期",
    "几月几号",
    "星期",
    "周",
]

HISTORICAL_HINTS = [
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


def _contains_any(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    return any(kw in text for kw in keywords)


def _requires_current_date_anchoring(query: str) -> bool:
    if not query or not query.strip():
        return False
    if (
        _contains_any(query, HISTORICAL_HINTS)
        and not _contains_any(query, RELATIVE_TIME_KEYWORDS)
        and not _contains_any(query, CALENDAR_KEYWORDS)
    ):
        return False
    return (
        _contains_any(query, RELATIVE_TIME_KEYWORDS)
        or _contains_any(query, FRESH_INFORMATION_KEYWORDS)
        or _contains_any(query, CALENDAR_KEYWORDS)
    )


def _derive_temporal_hint(query: str) -> str:
    if _contains_any(query, ["明天", "明日"]):
        return "明天"
    if _contains_any(query, ["昨天", "昨日", "前天"]):
        return "昨天"
    if _contains_any(query, ["本周", "这周"]):
        return "本周"
    if _contains_any(query, ["本月", "这个月"]):
        return "本月"
    if _contains_any(query, ["今年", "本年度", "本季度"]):
        return "今年"
    if _contains_any(query, ["最新", "实时", "当前", "现在", "目前", "刚刚"]):
        return "最新"
    return "今天"


def build_effective_search_query(query: str, current_date: str) -> str:
    """构建有效搜索查询（合并时间上下文）"""
    if not query or not query.strip():
        return query
    trimmed = query.strip()
    if not current_date:
        return trimmed
    if not _requires_current_date_anchoring(trimmed):
        return trimmed
    if trimmed.find(current_date) != -1 or _contains_any(trimmed, HISTORICAL_HINTS):
        return trimmed
    return f"{trimmed} {current_date} {_derive_temporal_hint(trimmed)}"


def _enrich_query_with_date(query: str) -> str:
    """时间锚定：追加当前日期让模型感知时间上下文"""
    today = date.today()
    date_text = f"{today.year}年{today.month}月{today.day}日"
    enriched = build_effective_search_query(query, date_text)
    if len(enriched) > 500:
        return query
    return enriched


# ── topic 校验 ──────────────────────────────────────────────────────────────


def _resolve_topic(requested_topic: str | None) -> str:
    """校验并标准化 topic：仅允许 general/news/finance，自动回退 general"""
    if requested_topic and requested_topic.strip().lower() in ALLOWED_TOPICS:
        return requested_topic.strip().lower()
    configured = settings.tavily.topic
    if configured and configured.strip().lower() in ALLOWED_TOPICS:
        return configured.strip().lower()
    if configured:
        logger.warning("tavily default topic invalid", topic=configured, fallback="general")
    return "general"


# ── 主工具函数 ─────────────────────────────────────────────────────────────────


async def tavily_search(
    query: str,
    topic: str | None = None,
    max_results: int | None = None,
    include_answer: bool | None = None,
    task_info: Any | None = None,
) -> dict:
    """
    调用 Tavily Search API。

    Args:
        query: 搜索查询（自动追加时间锚定）
        topic: 搜索话题 general/news/finance
        max_results: 最多返回结果数
        include_answer: 是否包含 Tavily AI 直接回答
        task_info: 可选的 ChatTaskInfo，用于跟踪计数

    Returns:
        {"answer": str, "results": [{"title", "url", "content"}], "error": str | None}
    """
    if not query or not query.strip():
        raise ValueError("query 不能为空")

    if not settings.tavily.enabled:
        raise RuntimeError("Tavily 搜索工具当前已禁用")

    if not settings.tavily.api_key:
        raise RuntimeError("Tavily API Key 未配置")

    s = settings.tavily
    enriched_query = _enrich_query_with_date(query)
    resolved_topic = _resolve_topic(topic)
    resolved_max_results = (
        max_results if max_results is not None and max_results > 0 else s.max_results
    )
    resolved_include_answer = include_answer if include_answer is not None else s.include_answer

    start_ms = int(asyncio.get_event_loop().time() * 1000)

    max_retries = TAVILY_SETTINGS.max_retries
    for attempt in range(max_retries + 1):
        try:
            client = _get_tavily_client()
            resp = await client.post(
                f"{s.base_url}{s.search_path}",
                json={
                    "query": enriched_query,
                    "topic": resolved_topic,
                    "search_depth": s.search_depth,
                    "max_results": resolved_max_results,
                    "include_answer": resolved_include_answer,
                    "include_raw_content": s.include_raw_content,
                },
                headers={
                    "Authorization": f"Bearer {s.api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if task_info:
                task_info.tool_call_count += 1

            duration_ms = int(asyncio.get_event_loop().time() * 1000) - start_ms
            logger.info(
                "tavily search success",
                query=enriched_query[:50],
                topic=resolved_topic,
                result_count=len(data.get("results", [])),
                duration_ms=duration_ms,
            )
            return data

        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            if attempt >= max_retries:
                logger.warning(
                    "tavily search exhausted retries", query=enriched_query[:50], error=str(e)
                )
                return {"answer": "", "results": [], "error": str(e)}

            delay_ms = min(
                TAVILY_SETTINGS.retry_initial_delay_ms * (2**attempt),
                TAVILY_SETTINGS.retry_max_delay_ms,
            )
            delay_ms += random.randint(0, 100)
            logger.warning(
                "tavily search retry",
                attempt=attempt + 1,
                delay_ms=delay_ms,
                error=str(e),
            )
            await asyncio.sleep(delay_ms / 1000)

        except Exception as e:
            logger.exception("tavily search unexpected error", query=enriched_query[:50])
            return {"answer": "", "results": [], "error": str(e)}

    return {"answer": "", "results": []}
