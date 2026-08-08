"""
查询重写 + 子问题拆分 + AnswerHistoryContext 组装

功能：
- needsRewrite: 判断是否需要 LLM 改写
- looksLikeExplicitMultiQuestion: 多问题模式检测
- parse: JSON 解析 (rewrite / should_split / sub_questions)
- normalizeRewriteResult: LLM 结果与规则拆分的调解
- ruleBasedSplit: 规则兜底拆分
- fallback: 不改写时的回退
- AnswerHistoryContext 组装 (合并自 AnswerHistoryContextAssembler)
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── multi-question detection patterns ──────────────────────────────────
_MULTI_QUESTION_DELIMITERS = {"；", ";"}
_NUMBERED_MULTI_PATTERN = r"(^|\s)(\d+[)\.、]|[A-Za-z][)])"


def _looks_like_explicit_multi_question(question: str) -> bool:
    normalized = (question or "").strip()
    if not normalized:
        return False
    question_mark_count = normalized.count("?") + normalized.count("？")
    if question_mark_count >= 2:
        return True
    if any(d in normalized for d in _MULTI_QUESTION_DELIMITERS):
        return True
    lines = [l.strip() for l in normalized.split("\n") if l.strip()]
    if len(lines) >= 2:
        return True

    if re.search(_NUMBERED_MULTI_PATTERN, normalized):
        return True
    return "分别" in normalized


def _needs_rewrite(question: str, history_summary: str) -> bool:
    history = (history_summary or "").strip()
    if not history:
        return len(question) < 8 or _looks_like_explicit_multi_question(question)
    return len(question) < 18 or _looks_like_explicit_multi_question(question)


def _rule_based_split(question: str, max_count: int = 4) -> list[str]:
    result = [s.strip() for s in re.split(r"[?？；;\n]+", question) if s.strip()]
    result = list(dict.fromkeys(result))  # dedup keep order
    if not result:
        return [question]
    return result[:max_count]


# ── AnswerHistoryContext follow-up hints ─────────────────────────────────
_FOLLOW_UP_HINTS = {
    "刚才",
    "上面",
    "前面",
    "前文",
    "上一条",
    "上一个",
    "上一轮",
    "这个",
    "那个",
    "这条",
    "那条",
    "继续",
    "展开",
    "补充",
    "详细",
    "细说",
    "进一步",
    "为什么",
    "怎么做",
    "怎么理解",
    "还有呢",
}

_FOLLOW_UP_ORDINAL_PATTERN = r"第\s*[0-9一二三四五六七八九十百]+\s*(条|点|项)"


def _looks_like_follow_up_question(normalized_question: str, has_recent_context: bool) -> bool:
    if not has_recent_context or not normalized_question:
        return False
    if any(h in normalized_question for h in _FOLLOW_UP_HINTS):
        return True

    if re.search(_FOLLOW_UP_ORDINAL_PATTERN, normalized_question):
        return True
    if len(normalized_question) <= 12:
        return True
    return len(normalized_question) <= 18 and (
        normalized_question.endswith("呢") or normalized_question.endswith("吗")
    )


def _extract_recent_user_questions(answer_recent_transcript: str) -> str:
    normalized = (answer_recent_transcript or "").strip()
    normalized = re.sub(r"^【最近相关对话】\s*", "", normalized)
    normalized = re.sub(r"^最近相关对话：\s*", "", normalized)
    lines = []
    for line in normalized.split("\n"):
        trimmed = line.strip()
        if trimmed.startswith("用户："):
            lines.append(trimmed)
    return "\n".join(lines).strip()


def _clip_tail(text: str, max_chars: int) -> str:
    normalized = (text or "").strip()
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 1:
        return ""
    start = max(0, len(normalized) - (max_chars - 1))
    return "…" + normalized[start:]


@dataclass
class RewriteResult:
    rewritten: str
    sub_questions: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)  # 搜索关键词/技术术语
    is_ambiguous: bool = False
    clarification_hint: str | None = None
    raw_model_output: str | None = None


@dataclass
class AnswerHistoryContextResult:
    rendered_text: str = ""
    structured_context: str = ""
    recent_context: str = ""
    follow_up_question: bool = False
    total_budget: int = 0
    recent_budget: int = 0
    structured_budget: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.rendered_text.strip()


class ChatQueryRewriteService:
    """
    查询重写服务。两阶段：
    1. 指代消解 — 结合最近对话补全省略成分
    2. 子问题拆分 — 复合问题拆成独立检索单元
    同时包含 AnswerHistoryContext 组装逻辑。
    """

    SYSTEM_PROMPT = """你是一个面向 RAG 文档检索的查询改写专家。

任务：将【用户问题】改写为更适合向量检索和关键词检索的形式。
输出要求：只返回 JSON，不要输出额外解释。

JSON 格式：
{
  "rewrite": "改写后的独立问题（完整、书面的检索语句）",
  "should_split": false,
  "sub_questions": ["子问题1", "子问题2"],
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "is_ambiguous": false,
  "clarification_hint": ""
}

改写规则（rewrite）：
1. 做指代消解、上下文补全、口语转书面化
2. 专有名词、技术术语（如 FastMCP、JWT、Depends、UploadFile 等）必须原样保留
3. 将模糊表达改为具体技术术语（如"那个参数"→"Depends 的参数"）
4. 不要发散扩写，不要添加原文没有的条件
5. 如果当前问题已经完整清晰，尽量少改

关键词规则（keywords）：
1. 提取 2-5 个最能描述问题核心的技术关键词/术语
2. 包含关键的技术名词、API 名称、框架名（如 FastMCP, Depends, JWT, tool, resource）
3. 关键词用于辅助向量检索，应选择文档中可能出现的高频技术词汇
4. 如果问题中文为主，关键词可以用中文

拆分规则（sub_questions）：
1. 默认 should_split=false，sub_questions 只保留 1 条
2. 只有原文显式存在多个独立问题时才拆分（多个问号、分号、换行、编号、明确"分别"）
3. 抽象对比、笼统追问一律不拆分"""

    def __init__(self) -> None:
        from app.common.llm_client import get_chat_client

        self._client = get_chat_client()

    async def rewrite(
        self,
        question: str,
        memory_ctx: Any = None,
        intent: str = "knowledge",
        history_summary: str = "",
        force: bool = False,
    ) -> RewriteResult:
        """
        重写入口。force=True 时跳过 _needs_rewrite 检查，始终调用 LLM（用于评估场景）。
        """
        normalized_question = (question or "").strip()
        if not normalized_question:
            return RewriteResult(rewritten="", sub_questions=[], keywords=[])

        # Build history summary from memory context if not explicitly provided
        if not history_summary and memory_ctx and hasattr(memory_ctx, "to_prompt_text"):
            history_summary = memory_ctx.to_prompt_text()

        if not settings.rag.rewrite_enabled or (
            not force and not _needs_rewrite(normalized_question, history_summary)
        ):
            return RewriteResult(
                rewritten=normalized_question,
                sub_questions=[normalized_question],
                keywords=[],
            )

        # ── LLM rewrite ───────────────────────────────────────────────
        history_context = (history_summary or "").strip()
        # limit history turns budget per configuration
        rewrite_budget = max(200, settings.rag.rewrite_history_turns * 550)
        if len(history_context) > rewrite_budget:
            history_context = _clip_tail(history_context, rewrite_budget)
        prompt = f"【最近对话】\n{history_context or '无历史上下文'}\n\n【用户问题】\n{normalized_question}"

        raw_output = ""
        try:
            from app.common.llm_client import llm_breaker

            create_kwargs: dict = {
                "model": settings.llm.model,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": settings.rag.rewrite_temperature,
                "top_p": settings.rag.rewrite_top_p,
                "response_format": {"type": "json_object"},
                "extra_body": {"thinking": {"type": "disabled"}},
            }
            if settings.rag.rewrite_thinking:
                create_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
            async with llm_breaker():
                response = await self._client.chat.completions.create(**create_kwargs)
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")
            raw_output = content
            parsed = self._parse(content)
            result = self._normalize_rewrite_result(normalized_question, parsed, history_summary)
            if result and result.rewritten:
                result.raw_model_output = raw_output
                logger.info(
                    "RAG 改写完成",
                    question=normalized_question[:50],
                    rewritten=result.rewritten[:50],
                    sub_count=len(result.sub_questions),
                )
                return result
            logger.warning(
                "RAG 改写结果不可用，回退到规则改写",
                question=normalized_question[:50],
                raw=(raw_output or "")[:50],
            )
        except Exception as e:
            logger.warning(
                "RAG 改写失败，回退到规则改写",
                question=normalized_question[:50],
                error=str(e),
                exc_info=True,
            )

        # ── 规则拆分回退 ─────────────────────────────────────────────────
        rule_split = _rule_based_split(normalized_question, settings.rag.max_sub_questions)
        sub_qs = rule_split if len(rule_split) > 1 else [normalized_question]
        if len(sub_qs) > 1:
            logger.info(
                "RAG 改写回退到规则拆分",
                question=normalized_question[:50],
                sub_count=len(sub_qs),
            )
        return RewriteResult(
            rewritten=normalized_question,
            sub_questions=sub_qs,
            keywords=[],
        )

    def _parse(self, raw: str) -> dict | None:
        """解析 LLM 返回的 JSON。"""
        if not raw or not raw.strip():
            return None
        try:
            root = json.loads(raw.strip())
            rewrite = (root.get("rewrite", "") or "").strip()
            if not rewrite:
                return None
            should_split = root.get("should_split") if "should_split" in root else None
            sub_questions_raw = root.get("sub_questions")
            sub_questions = []
            if isinstance(sub_questions_raw, list):
                sub_questions = [str(s).strip() for s in sub_questions_raw if str(s).strip()]
            keywords_raw = root.get("keywords")
            keywords = []
            if isinstance(keywords_raw, list):
                keywords = [str(k).strip() for k in keywords_raw if str(k).strip()]
            return {
                "rewrite": rewrite,
                "should_split": should_split,
                "sub_questions": sub_questions,
                "keywords": keywords,
            }
        except Exception as e:
            logger.warning("解析问题改写 JSON 失败", raw=raw[:100], error=str(e), exc_info=True)
            return None

    def _normalize_rewrite_result(
        self,
        original_question: str,
        parsed: dict | None,
        history_summary: str = "",
    ) -> RewriteResult | None:
        """调解 LLM 输出与规则拆分的冲突。"""
        if not parsed:
            return None

        rewrite = parsed["rewrite"]
        if not rewrite:
            return None

        should_split_val = parsed.get("should_split")
        sub_questions = [s for s in parsed.get("sub_questions", []) if s]
        keywords = [k for k in parsed.get("keywords", []) if k]

        explicit_multi = _looks_like_explicit_multi_question(original_question)
        should_split = bool(should_split_val) if should_split_val is not None else explicit_multi

        if not should_split and not explicit_multi:
            sub_questions = [rewrite]
        elif not sub_questions and not should_split:
            fallback_split = _rule_based_split(original_question, settings.rag.max_sub_questions)
            sub_questions = fallback_split if len(fallback_split) > 1 else [rewrite]
        elif not sub_questions:
            sub_questions = [rewrite]

        # 只有 1 个子问题且不是 rewrite 且不应该 split，收敛为 rewrite
        if len(sub_questions) == 1 and sub_questions[0] != rewrite and not should_split:
            sub_questions = [rewrite]

        max_sub = settings.rag.max_sub_questions
        if len(sub_questions) > max_sub:
            sub_questions = sub_questions[:max_sub]

        return RewriteResult(
            rewritten=rewrite,
            sub_questions=sub_questions,
            keywords=keywords,
        )

    # ── AnswerHistoryContext 组装 ────────────────────────────────────────────

    def _assemble_answer_history(
        self,
        question: str,
        answer_recent_transcript: str,
    ) -> AnswerHistoryContextResult:
        normalized_question = (question or "").strip()
        recent_user_context = _extract_recent_user_questions(answer_recent_transcript)
        total_budget = max(1, settings.rag.answer_history_max_chars)
        has_recent_context = bool(recent_user_context.strip())
        follow_up = _looks_like_follow_up_question(normalized_question, has_recent_context)

        if not follow_up or not has_recent_context:
            return AnswerHistoryContextResult(
                total_budget=total_budget,
                follow_up_question=follow_up,
            )

        recent_part = self._render_recent_context(recent_user_context, total_budget)
        if not recent_part.strip():
            return AnswerHistoryContextResult(
                total_budget=total_budget,
                follow_up_question=follow_up,
            )

        return AnswerHistoryContextResult(
            rendered_text=recent_part,
            structured_context="",
            recent_context=recent_part,
            follow_up_question=follow_up,
            total_budget=total_budget,
            recent_budget=total_budget,
            structured_budget=0,
        )

    def _render_recent_context(self, recent_user_context: str, budget: int) -> str:
        if budget <= 0 or not recent_user_context.strip():
            return ""
        title = "对话承接上下文（仅用于理解指代，不作为事实证据）：\n"
        if budget <= len(title):
            return _clip_tail(recent_user_context, budget)
        body = _clip_tail(recent_user_context, budget - len(title))
        if not body.strip():
            return ""
        return title + body
