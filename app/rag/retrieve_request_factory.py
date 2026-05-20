"""
检索请求构建工厂
包含：QueryAugmentation（导航提示 + 历史上下文提示）、
Filters（年份/章节/文档名/业务分类/标签）、
短追问检测、有意义词条提取
"""

import re

import structlog

from app.chat.schema import ExecutionPlan

logger = structlog.get_logger(__name__)

# ── 正则 ──────────────────────────────────────────────────────────────────
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
_SECTION_PATTERN = re.compile(
    r"(第\s*[一二三四五六七八九十百\d]+\s*[章节条部分])|(附录\s*[A-Za-z一二三四五六七八九十\d]+)"
)

# ── 过滤器提示词 ──────────────────────────────────────────────────────────
_DOCUMENT_NAME_HINTS = [
    "部署手册",
    "配置手册",
    "操作手册",
    "用户手册",
    "快速开始",
    "接入指南",
    "FAQ",
    "常见问题",
    "说明文档",
    "说明书",
    "规范",
    "指南",
    "手册",
    "文档",
]

_BUSINESS_CATEGORY_HINTS: list[str] = []

_DOCUMENT_TAG_HINTS: list[str] = []

# ── 短追问检测词 ──────────────────────────────────────────────────────────
_SHORT_FOLLOW_UP_HINTS = {"它", "这个", "那个", "刚才", "前面", "上面"}


class DocumentRetrieveRequestFactory:
    """
    构建检索请求：将编排阶段的决策映射到实际子问题过滤条件。
    """

    async def build(self, plan: ExecutionPlan) -> ExecutionPlan:
        """
        为每个子问题构建增强的检索查询 + 过滤条件。
        直接修改 plan.sub_questions 并返回。
        """
        for sub_q in plan.sub_questions:
            normalized_question = (sub_q.text or "").strip()
            if not normalized_question:
                continue

            # ── 1. QueryAugmentation：导航提示 + 历史上下文提示 + 搜索关键词 ──
            retrieval_query, query_context_hints = self._build_query_augmentation(
                normalized_question, plan, sub_q.query_context_hints
            )
            # Store augmented query back (retrieval_query overrides original text)
            sub_q.text = retrieval_query

            # ── 2. Filters：年份/章节/文档名/业务分类/标签 ─────────────────
            filters = self._build_filters(normalized_question)
            if filters.get("document_name_hints"):
                sub_q.document_name_hints = filters["document_name_hints"]
            if filters.get("business_category_hints"):
                sub_q.business_category_hints = filters["business_category_hints"]
            if filters.get("document_tag_hints"):
                sub_q.document_tag_hints = filters["document_tag_hints"]
            if filters.get("year_hints"):
                sub_q.year_hints = filters["year_hints"]

            # ── 3. 导航段文档ID注入 ────────────────────────────────────────
            if plan.selected_document_id and not sub_q.doc_ids:
                sub_q.doc_ids = [plan.selected_document_id]

            logger.info(
                "检索请求构造",
                sub_question=normalized_question[:50],
                retrieval_query=retrieval_query[:100],
                section_hints=filters.get("section_path_hints", []),
                year_hints=filters.get("year_hints", []),
                query_context_hints=query_context_hints,
            )

        return plan

    def _build_query_augmentation(
        self,
        normalized_question: str,
        plan: ExecutionPlan,
        sub_q_hints: list[str] | None = None,
    ) -> tuple[str, list[str]]:
        """构建检索查询增强：合并导航提示、历史上下文和搜索关键词。"""
        # 搜索关键词（来自查询改写）
        keyword_hints = [h.strip() for h in (sub_q_hints or []) if h.strip()]
        keyword_hints = list(dict.fromkeys(keyword_hints))[:5]

        # 导航提示
        navigation_hints: list[str] = []
        if plan.navigation_decision:
            nav = plan.navigation_decision
            if nav.structure_anchor:
                title = nav.structure_anchor.section_title
                if title:
                    navigation_hints.append(title)
            if nav.item_anchor and nav.item_anchor.item_index is not None:
                navigation_hints.append(f"第{nav.item_anchor.item_index}步")
                navigation_hints.append(f"第{nav.item_anchor.item_index}项")
        navigation_hints = list(dict.fromkeys([h.strip() for h in navigation_hints if h.strip()]))[
            :4
        ]

        if not self._looks_like_short_follow_up(normalized_question):
            all_hints = keyword_hints + navigation_hints
            if not all_hints:
                return normalized_question, self._extract_meaningful_terms(normalized_question)
            retrieval_query = f"{normalized_question} {' '.join(all_hints)}"
            query_hints = all_hints + self._extract_meaningful_terms(normalized_question)
            return retrieval_query, list(dict.fromkeys(query_hints))[:8]

        # 短追问 + 历史上下文增强
        history_hints: list[str] = []
        if plan.history_planning_context:
            ctx = plan.history_planning_context
            history_hints = [h.strip() for h in (ctx.retrieval_hints or []) if h.strip()]
            history_hints = list(dict.fromkeys(history_hints))[:4]

        all_hints = keyword_hints + history_hints + navigation_hints
        if not all_hints:
            return normalized_question, self._extract_meaningful_terms(normalized_question)

        retrieval_query = f"{normalized_question} {' '.join(all_hints)}"
        query_context_hints = all_hints + self._extract_meaningful_terms(normalized_question)
        return retrieval_query, list(dict.fromkeys(query_context_hints))[:8]

    def _build_filters(self, question: str) -> dict:
        """从问题中提取过滤维度。"""
        if not question or not question.strip():
            return {}

        normalized = question.lower()

        document_name_hints = []
        business_category_hints = []
        document_tag_hints = []
        section_path_hints = []
        year_hints = []

        for m in _YEAR_PATTERN.finditer(question):
            year_hints.append(m.group(1))
        for m in _SECTION_PATTERN.finditer(question):
            text = (m.group() or "").replace(" ", "")
            if text:
                section_path_hints.append(text)
        for hint in _DOCUMENT_NAME_HINTS:
            if hint.lower() in normalized:
                document_name_hints.append(hint)
        for hint in _BUSINESS_CATEGORY_HINTS:
            if hint.lower() in normalized:
                business_category_hints.append(hint)
        for hint in _DOCUMENT_TAG_HINTS:
            if hint.lower() in normalized:
                document_tag_hints.append(hint)

        return {
            "document_name_hints": document_name_hints,
            "business_category_hints": business_category_hints,
            "document_tag_hints": document_tag_hints,
            "section_path_hints": section_path_hints,
            "year_hints": year_hints,
        }

    def _looks_like_short_follow_up(self, question: str) -> bool:
        if not question or not question.strip():
            return False
        normalized = (question or "").strip()
        if len(normalized) < 12:
            return True
        return any(hint in normalized for hint in _SHORT_FOLLOW_UP_HINTS)

    def _extract_meaningful_terms(self, question: str) -> list[str]:
        if not question or not question.strip():
            return []
        terms = []
        seen = set()
        for segment in re.split(r"[\s、，,；;：:（）()\-的和及与或]+", question):
            trimmed = segment.strip()
            if len(trimmed) >= 2 and trimmed not in seen:
                seen.add(trimmed)
                terms.append(trimmed)
        return terms[:6]
