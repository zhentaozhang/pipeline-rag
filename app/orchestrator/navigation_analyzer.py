"""
文档结构导航分析器
包含：章节号解析、局部结构评分、邻接/大纲/条款/分析性检测、中文数字解析、查询提示构建

通过章节号解析、局部结构评分、邻接/大纲/条款检测，判断文档内导航意图。
"""

import re
from enum import Enum
from typing import Any

import structlog

from app.chat.schema import DocumentNavigationDecision, ItemAnchor, StructureAnchor
from app.common.text_utils import first_non_blank, normalize_step_numeral, safe_text
from app.common.utils import safe_int

logger = structlog.get_logger(__name__)

# ── 正则 ──────────────────────────────────────────────────────────────────
_SECTION_CODE_PATTERN = re.compile(r"(\d+(?:\.\d+)+)")
_STEP_REFERENCE_PATTERN = re.compile(r"第\s*([0-9一二三四五六七八九十百]+)\s*步")
_ORDINAL_REFERENCE_PATTERN = re.compile(r"第\s*([0-9一二三四五六七八九十百]+)\s*(条|点|项|个)")
_QUOTED_TEXT_PATTERN = re.compile(r'["\u201c\u201d]([^\u201c\u201d]{2,40})["\u201c\u201d]')


# ── 提示词列表 ────────────────────────────────────────────────────────────
_ADJACENCY_HINTS = [
    "上一节",
    "下一节",
    "前一节",
    "后一节",
    "上一个章节",
    "下一个章节",
    "属于哪个章节",
    "章节位置",
]

_OUTLINE_HINTS = [
    "包含哪些章节",
    "都包含哪些章节",
    "有哪些章节",
    "有哪些小节",
    "包含哪些小节",
    "章节列表",
    "目录",
]

_ITEM_HINTS = ["哪一步", "哪一项", "第几步", "第几项", "具体步骤", "步骤中的"]

_ANALYTIC_HINTS = [
    "关系",
    "关联",
    "为什么",
    "原因",
    "可能原因",
    "影响",
    "区别",
    "对比",
    "比较",
    "如何理解",
    "怎么理解",
    "说明了什么",
    "是否意味着",
    "是否说明",
    "分析",
    "解释",
]

_CN_DIGIT_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_chinese_number(val: str) -> int | None:
    normalized = safe_text(val)
    if not normalized:
        return None
    res = safe_int(normalized, default=None)
    if res is not None:
        return res
    if "十" not in normalized:
        return _CN_DIGIT_MAP.get(normalized)
    if normalized == "十":
        return 10
    if normalized.startswith("十") and len(normalized) == 2:
        return 10 + _CN_DIGIT_MAP.get(normalized[1], 0)
    if normalized.endswith("十") and len(normalized) == 2:
        return _CN_DIGIT_MAP.get(normalized[0], 0) * 10
    if "十" in normalized and len(normalized) == 3:
        return _CN_DIGIT_MAP.get(normalized[0], 0) * 10 + _CN_DIGIT_MAP.get(normalized[2], 0)
    return _CN_DIGIT_MAP.get(normalized[0])


class DocumentNavigationAction(Enum):
    TOPIC_CONTINUE = "TOPIC_CONTINUE"
    TOPIC_SWITCH = "TOPIC_SWITCH"
    FRESH_TOPIC = "FRESH_TOPIC"
    SIBLING_SECTION_SWITCH = "SIBLING_SECTION_SWITCH"
    CHILD_SECTION_DESCEND = "CHILD_SECTION_DESCEND"
    ANCESTOR_SECTION_RETURN = "ANCESTOR_SECTION_RETURN"
    ITEM_REFERENCE = "ITEM_REFERENCE"
    SECTION_ADJACENCY_LOOKUP = "SECTION_ADJACENCY_LOOKUP"


class RetrievalQuestionPlan:
    """检索子问题列表（改写后的检索问题 + 拆分后的子问题）"""

    def __init__(self, retrieval_question: str, sub_questions: list[str]):
        self.retrieval_question = retrieval_question
        self.sub_questions = sub_questions


class RewriteResult:
    """改写结果（改写后的问题 + 子问题列表）"""

    def __init__(
        self, rewritten_question: str | None = None, sub_questions: list[str] | None = None
    ):
        self.rewritten_question = rewritten_question
        self.sub_questions = sub_questions


async def analyze(
    doc_id: str | None,
    original_question: str,
    rewrite_result: Any = None,
) -> DocumentNavigationDecision | None:
    """
    文档路由分析入口。

    Args:
        doc_id: 目标文档 ID
        original_question: 原始问题
        rewrite_result: 改写结果，包含 rewrittenQuestion + subQuestions

    Returns:
        DocumentNavigationDecision | None
    """
    # ── 1. 提取 rewrittenQuestion ────────────────────────────────────────────
    rewrote = None
    if rewrite_result is not None:
        if hasattr(rewrite_result, "rewritten_question") and rewrite_result.rewritten_question:
            rewrote = rewrite_result.rewritten_question
        elif hasattr(rewrite_result, "rewritten") and rewrite_result.rewritten:
            rewrote = rewrite_result.rewritten
    rewritten_question = first_non_blank(rewrote, original_question)

    # ── 2. 归一化 subQuestions ───────────────────────────────────────────────
    sub_questions = _normalize_sub_questions(rewrite_result, rewritten_question)

    # ── 3. 构建 RetrievalQuestionPlan ─────────────────────────────────────────
    retrieval_plan = RetrievalQuestionPlan(rewritten_question, sub_questions)

    # ── 4. 构建 routeText = original + ' ' + rewritten ────────────────────────
    route_text = (f"{safe_text(original_question)} {rewritten_question}").strip()

    # ── 4.5 归一化中文数字步骤（第二步 → 第2步）──────────
    route_text = normalize_step_numeral(route_text)
    original_question = normalize_step_numeral(original_question)
    rewritten_question = normalize_step_numeral(rewritten_question)

    # ── 5. 检测分析性问题 ─────────────────────────────────────────────────────
    analytic_question = _looks_analytic_question(route_text)

    # ── 6. 邻接/大纲 → GRAPH_ONLY ─────────────────────────────────────────────
    asks_adjacency = _asks_adjacency(route_text)
    asks_outline = _asks_outline(route_text)

    if (asks_adjacency or asks_outline) and not analytic_question and len(sub_questions) <= 1:
        section = await _resolve_section(doc_id, original_question, rewritten_question)
        action = "SECTION_ADJACENCY_LOOKUP" if asks_adjacency else "CHILD_SECTION_DESCEND"
        return _build_decision(
            execution_mode="GRAPH_ONLY",
            action=action,
            section=section,
            item_index=None,
            retrieval_plan=retrieval_plan,
            reason="结构型问题直接走图查询",
        )

    # ── 7. 编号项/步骤 → GRAPH_THEN_EVIDENCE ─────────────────────────────────
    item_index = _resolve_explicit_item_index(route_text)
    asks_item_lookup = _asks_item_lookup(route_text)

    if (item_index is not None or asks_item_lookup) and not analytic_question:
        section = await _resolve_section(doc_id, original_question, rewritten_question)
        # 验证 section 是否匹配 item_index（避免 ES 模糊匹配到错误章节）
        _section_contains_item = (
            section
            and section.get("contentText")
            and item_index is not None
            and f"第{item_index}步" in (section.get("contentText", "") or "")
        )
        if section and section.get("id") and (item_index is None or _section_contains_item):
            return _build_decision(
                execution_mode="GRAPH_THEN_EVIDENCE",
                action="ITEM_REFERENCE",
                section=section,
                item_index=item_index,
                retrieval_plan=retrieval_plan,
                reason="编号项或步骤型问题走图定位取证",
            )
        # section 不可用或与 item_index 不匹配，降级为 RETRIEVAL
        logger.info(
            "section not resolved for item query, fallback to retrieval",
            doc_id=doc_id,
            item_index=item_index,
            section_has_content=bool(section.get("contentText") if section else False),
            section_contains_item=_section_contains_item if section else False,
        )

    # ── 8. 软提示 → RETRIEVAL ─────────────────────────────────────────────────
    mentions_structure = _mentions_structure(route_text)
    assisted_section = None
    if analytic_question or asks_outline or item_index is not None or mentions_structure:
        assisted_section = await _resolve_section(doc_id, original_question, rewritten_question)

    retrieval_action = "ITEM_REFERENCE" if item_index is not None else "FRESH_TOPIC"
    return _build_decision(
        execution_mode="RETRIEVAL",
        action=retrieval_action,
        section=assisted_section,
        item_index=item_index,
        retrieval_plan=retrieval_plan,
        reason=(
            "普通文档问题走混合检索"
            if assisted_section is None
            else "结构线索仅作为软提示辅助混合检索"
        ),
    )


# ── buildDecision ──────────────────────────────────────────────────────


def _build_decision(
    execution_mode: str,
    action: str,
    section: Any,
    item_index: int | None,
    retrieval_plan: RetrievalQuestionPlan,
    reason: str,
) -> DocumentNavigationDecision:
    """构建 DocumentNavigationDecision。"""

    # 构建 StructureAnchor
    if section is None:
        scope_mode = "NONE" if execution_mode == "RETRIEVAL" else "GRAPH_UNRESOLVED"
        structure_anchor = StructureAnchor(scope_mode=scope_mode)
    else:
        scope_mode = "SOFT" if execution_mode == "RETRIEVAL" else "GRAPH"
        structure_anchor = StructureAnchor(
            root_section_code=section.get("code", ""),
            root_section_title=section.get("title", ""),
            target_section_hint=section.get("title", ""),
            structure_node_id=str(section.get("id", "")) if section.get("id") else None,
            canonical_path=section.get("path", ""),
            scope_mode=scope_mode,
        )

    # 构建 ItemAnchor
    item_anchor = ItemAnchor(item_index=item_index) if item_index is not None else None

    # 构建 queryHints
    query_context_hints = _build_query_hints(retrieval_plan, section, item_index)

    # 构建 summaryText
    section_display = (
        section.get("title", "") if isinstance(section, dict) else (str(section) if section else "")
    )
    summary_text = (
        f"mode={execution_mode}; reason={reason}"
        f"; section={section_display}"
        f"; itemIndex={item_index if item_index is not None else ''}"
    )

    # softSectionHints
    soft_section_hints = [section_display] if section_display else []

    logger.info(
        "文档问答路由完成",
        mode=execution_mode,
        action=action,
        section=section_display,
        item_index=item_index,
        reason=reason,
    )

    return DocumentNavigationDecision(
        execution_mode=execution_mode,
        action=action,
        navigation_action=action,
        structure_anchor=structure_anchor,
        item_anchor=item_anchor,
        summary_text=summary_text,
        query_context_hints=query_context_hints,
        soft_section_hints=soft_section_hints,
    )


# ── resolveSection ──────────────────────────────────────────────────────


async def _resolve_section(
    doc_id: str | None, original_question: str, rewritten_question: str
) -> dict | None:
    """解析章节信息（先按章节号匹配，再按导航索引搜索）。"""
    if doc_id is None:
        return None
    # By section code
    by_code = _resolve_by_section_code(original_question, rewritten_question)
    if by_code is not None:
        return by_code
    # By navigation index
    by_index = await _resolve_by_navigation_index(doc_id, rewritten_question)
    if by_index is not None:
        return by_index
    return None


def _resolve_by_section_code(original_question: str, rewritten_question: str) -> dict | None:
    """从问题正则匹配章节编码（如 1.2.3）。"""
    text = f"{safe_text(original_question)} {safe_text(rewritten_question)}".strip()
    matcher = _SECTION_CODE_PATTERN.search(text)
    if matcher:
        return {"code": matcher.group(1), "title": matcher.group(1)}
    return None


async def _resolve_by_navigation_index(doc_id: str, query: str) -> dict | None:
    """通过 ES 导航索引搜索章节。"""
    try:
        from app.infra.es_services import ElasticsearchDocumentNavigationIndexService

        es_service = ElasticsearchDocumentNavigationIndexService()
        hits = await es_service.search_sections(
            doc_id=doc_id,
            query_texts=[query],
            size=5,
        )
        if hits:
            return hits[0]
    except Exception as e:
        logger.debug("ES navigation index search failed", error=str(e), exc_info=True)
    return None


# ── normalizeSubQuestions ─────────────────────────────────────────────


def _normalize_sub_questions(rewrite_result: Any, fallback_question: str) -> list[str]:
    """归一化子问题：去空、去重、回退到 fallback。"""
    sub_questions = None
    if rewrite_result is not None:
        if hasattr(rewrite_result, "sub_questions"):
            sub_questions = rewrite_result.sub_questions
    if not sub_questions:
        return [fallback_question]
    result = []
    for sq in sub_questions:
        t = (sq or "").strip()
        if t:
            result.append(t)
    seen = []
    for item in result:
        if item not in seen:
            seen.append(item)
    return seen if seen else [fallback_question]


# ── 提示检测 ──────────────────────────────────────────────────────────


def _asks_adjacency(question: str) -> bool:
    return any(h in question for h in _ADJACENCY_HINTS)


def _asks_outline(question: str) -> bool:
    return any(h in question for h in _OUTLINE_HINTS)


def _asks_item_lookup(question: str) -> bool:
    return any(h in question for h in _ITEM_HINTS)


def _looks_analytic_question(question: str) -> bool:
    normalized = safe_text(question)
    return any(h in normalized for h in _ANALYTIC_HINTS)


def _mentions_structure(question: str) -> bool:
    normalized = safe_text(question)
    return (
        "章节" in normalized
        or "小节" in normalized
        or "条目" in normalized
        or "步骤" in normalized
        or "项" in normalized
        or bool(_QUOTED_TEXT_PATTERN.search(normalized))
        or bool(_SECTION_CODE_PATTERN.search(normalized))
    )


def _resolve_explicit_item_index(question: str) -> int | None:
    """解析第N步 / 第N条索引（支持中文和阿拉伯数字）。"""
    text = safe_text(question)
    step_match = _STEP_REFERENCE_PATTERN.search(text)
    if step_match:
        return _parse_chinese_number(step_match.group(1))
    ordinal_match = _ORDINAL_REFERENCE_PATTERN.search(text)
    if ordinal_match:
        return _parse_chinese_number(ordinal_match.group(1))
    return None


# ── 辅助 ──────────────────────────────────────────────────────────────


def _build_query_hints(
    retrieval_plan: RetrievalQuestionPlan | None, section: Any, item_index: int | None
) -> list[str]:
    """构建查询上下文提示词（章节标题、编码、步骤索引）。"""
    hints = []
    seen = set()

    def add_hint(h: str) -> None:
        h = safe_text(h)
        if h and h not in seen:
            seen.add(h)
            hints.append(h)

    if retrieval_plan is not None:
        for seg in re.split(
            r"[\s、，,；;：:（）()\-的和及与或]+", safe_text(retrieval_plan.retrieval_question)
        ):
            t = seg.strip()
            if len(t) >= 2:
                add_hint(t)
    if section is not None:
        if isinstance(section, dict):
            add_hint(section.get("title", ""))
            add_hint(section.get("code", ""))
    if item_index is not None:
        add_hint(f"第{item_index}步")
        add_hint(f"第{item_index}项")

    return hints[:10]


def _detect_facet(question: str) -> str:
    """检测问题面向（章节位置/章节/步骤/分析）。"""
    if _asks_adjacency(question):
        return "章节位置"
    if _asks_outline(question):
        return "章节"
    if _asks_item_lookup(question):
        return "步骤"
    return ""
