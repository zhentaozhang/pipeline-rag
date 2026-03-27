"""
文档画像服务 (Document Profile Service)
启发式规则从文档结构、术语频率、引用密度等维度推断文档画像。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.document_repository import DocumentRepository
from app.infra.id_generator import next_id

if TYPE_CHECKING:
    from app.db.models.document import Document, DocumentProfile

logger = structlog.get_logger(__name__)

PROFILE_STATUS_SUCCESS = 2


async def generate_profile(db: AsyncSession, doc_id: str, parsed_text: str) -> None:
    """基于启发式规则推断文档画像"""
    logger.info("generating document profile heuristically", doc_id=doc_id)

    document = await DocumentRepository.get_by_doc_id(db, doc_id)
    if not document:
        logger.error("document not found for profile generation", doc_id=doc_id)
        return

    section_titles = _extract_section_titles(parsed_text)
    supports_item_lookup = _check_supports_item_lookup(parsed_text)
    supports_graph_outline = len(section_titles) >= 2
    graph_friendly = supports_item_lookup or supports_graph_outline
    document_type = _infer_document_type(
        document, parsed_text, section_titles, supports_item_lookup
    )
    core_topics = _build_core_topics(document, section_titles)
    example_questions = _build_example_questions(document_type, core_topics)
    summary = _build_summary(document, section_titles, parsed_text)
    knowledge_scope_code = _infer_knowledge_scope_code(document, section_titles, parsed_text)
    knowledge_scope_name = _infer_knowledge_scope_name(knowledge_scope_code)
    business_category = _infer_business_category(document_type, parsed_text)
    document_tags = _build_document_tags(document, knowledge_scope_code, document_type, core_topics)

    from app.db.models.document import DocumentProfile as DocProfile

    stmt = select(DocProfile).where(DocProfile.document_id == document.id)
    res = await db.execute(stmt)
    profile = res.scalar_one_or_none()

    creating = profile is None
    if creating:
        profile = DocProfile(
            id=next_id(),
            document_id=document.id,
            profile_version=1,
            profile_status=PROFILE_STATUS_SUCCESS,
            status=1,
        )
        db.add(profile)
    else:
        profile.profile_version = (profile.profile_version or 0) + 1

    profile.document_summary = summary
    profile.document_type = document_type
    profile.core_topics = json.dumps(core_topics, ensure_ascii=False)
    profile.example_questions = json.dumps(example_questions, ensure_ascii=False)
    profile.graph_friendly = graph_friendly
    profile.supports_graph_outline = supports_graph_outline
    profile.supports_item_lookup = supports_item_lookup
    profile.supports_graph_assist = True
    profile.knowledge_scope_code = knowledge_scope_code
    profile.knowledge_scope_name = knowledge_scope_name
    profile.business_category = business_category
    profile.document_tags = document_tags
    profile.profile_source = "auto"
    profile.profile_status = PROFILE_STATUS_SUCCESS
    profile.error_msg = None

    await db.flush()
    await db.commit()

    await _backfill_document_metadata(
        db,
        document,
        knowledge_scope_code,
        knowledge_scope_name,
        business_category,
        document_tags,
    )

    logger.info(
        "document profile generated",
        doc_id=doc_id,
        document_type=document_type,
        graph_friendly=graph_friendly,
        supports_item_lookup=supports_item_lookup,
        scope_code=knowledge_scope_code,
        business_category=business_category,
        tags=document_tags,
    )


# ── helper: section titles ──


def _extract_section_titles(parsed_text: str) -> list[str]:
    titles: list[str] = []
    for line in (parsed_text or "").split("\n"):
        stripped = line.strip()
        if re.match(r"^(#{1,6}\s+|第[一二三四五六七八九十百\d]+[章节条部分])", stripped):
            title = re.sub(r"^#{1,6}\s*", "", stripped)
            title = _SECTION_CODE_PATTERN.sub("", title).strip()
            if title and len(title) < 80:
                titles.append(title)
    unique: list[str] = []
    seen = set()
    for t in titles:
        if t not in seen:
            seen.add(t)
            unique.append(t)
            if len(unique) >= 8:
                break
    return unique


def _check_supports_item_lookup(parsed_text: str) -> bool:
    return bool(re.search(r"(^\d+[\.\、\)]|^第\d+[步条])", parsed_text or "", re.MULTILINE))


# ── type / scope / topic inference ──


def _infer_document_type(
    document: Document,
    parsed_text: str,
    section_titles: list[str],
    supports_item_lookup: bool,
) -> str:
    combined = _combined_text(document, parsed_text, section_titles)
    if "faq" in combined or "常见问题" in combined:
        return "faq"
    if _contains_any(combined, "故障", "排查", "检查顺序"):
        return "troubleshooting"
    if _contains_any(combined, "规则", "制度"):
        return "rule"
    if _contains_any(combined, "规格", "参数"):
        return "spec"
    if supports_item_lookup or _contains_any(combined, "手册", "指南", "部署"):
        return "manual"
    return "intro"


def _build_core_topics(document: Document, section_titles: list[str]) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()
    for title in section_titles[:6]:
        clean = _SECTION_CODE_PATTERN.sub("", title).strip()
        if clean and clean not in seen:
            seen.add(clean)
            topics.append(clean)
    name = _strip_extension(document.document_name or document.original_file_name or "")
    if name and name not in seen:
        seen.add(name)
        topics.append(name)
    return [t for t in topics if t][:6]


def _build_example_questions(document_type: str, core_topics: list[str]) -> list[str]:
    examples: list[str] = []
    for topic in core_topics:
        if document_type == "troubleshooting":
            examples.append(f"{topic}的可能原因有哪些？")
        elif document_type == "manual":
            examples.append(f"{topic}的步骤是什么？")
        elif document_type == "rule":
            examples.append(f"{topic}有哪些规则？")
        else:
            examples.append(f"{topic}是什么意思？")
    seen: set[str] = set()
    unique: list[str] = []
    for q in examples:
        if q not in seen:
            seen.add(q)
            unique.append(q)
    return unique[:6]


def _build_summary(document: Document, section_titles: list[str], parsed_text: str) -> str:
    name = document.document_name or document.original_file_name or "未命名文档"
    parts = [f"文档《{name}》"]
    if section_titles:
        parts.append("主要涵盖：" + "、".join(section_titles[:4]) + "。")
    excerpt = re.sub(r"\s+", " ", parsed_text or "").strip()
    if len(excerpt) > 180:
        excerpt = excerpt[:180]
    if excerpt:
        parts.append(f"摘要：{excerpt}")
    return "".join(parts).strip()


def _infer_knowledge_scope_code(
    document: Document, section_titles: list[str], parsed_text: str
) -> str:
    combined = _combined_text(document, parsed_text, section_titles)
    if _contains_any(combined, "上线观察", "值班规则", "观察时长", "运营"):
        return "operation_rule"
    if _contains_any(combined, "机器人", "知识召回", "意图识别", "策略设计"):
        return "robot_strategy"
    if _contains_any(combined, "安装", "部署", "默认密码", "访问地址"):
        return "deployment"
    if _contains_any(combined, "故障", "排查", "异常", "检查顺序"):
        return "troubleshooting"
    if _contains_any(combined, "产品简介", "核心特性", "技术规格", "产品概述"):
        return "product"
    return "general_document"


def _infer_knowledge_scope_name(scope_code: str) -> str:
    mapping = {
        "operation_rule": "运营规则",
        "robot_strategy": "机器人策略",
        "deployment": "安装部署",
        "troubleshooting": "故障排查",
        "product": "产品资料",
    }
    return mapping.get(scope_code or "", "通用文档")


def _infer_business_category(document_type: str, parsed_text: str) -> str:
    if document_type == "troubleshooting":
        return "故障排查"
    if document_type == "rule":
        return "规则"
    if document_type == "spec":
        return "规格说明"
    if document_type == "manual":
        return (
            "操作手册"
            if _contains_any((parsed_text or "").lower(), "步骤", "操作", "部署")
            else "手册"
        )
    return "介绍"


def _build_document_tags(
    document: Document, knowledge_scope_code: str, document_type: str, core_topics: list[str]
) -> str:
    tags: list[str] = []
    seen: set[str] = set()
    if document.document_tags:
        for t in document.document_tags.split(","):
            t = t.strip()
            if t and t not in seen:
                seen.add(t)
                tags.append(t)
    for tag in (knowledge_scope_code, document_type, *core_topics[:4]):
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return ",".join(tags[:8])


async def _backfill_document_metadata(
    db: AsyncSession,
    document: Document,
    scope_code: str,
    scope_name: str,
    business_category: str,
    document_tags: str,
) -> None:
    changed = False
    if not document.knowledge_scope_code and scope_code:
        document.knowledge_scope_code = scope_code
        changed = True
    if not document.knowledge_scope_name and scope_name:
        document.knowledge_scope_name = scope_name
        changed = True
    if not document.business_category and business_category:
        document.business_category = business_category
        changed = True
    if not document.document_tags and document_tags:
        document.document_tags = document_tags
        changed = True
    if changed:
        db.add(document)
        await db.flush()


# ── utils ──


def _combined_text(document: Document, parsed_text: str, section_titles: list[str]) -> str:
    return " ".join(
        [
            document.document_name or "",
            document.original_file_name or "",
            " ".join(section_titles),
            parsed_text or "",
        ]
    ).lower()


def _contains_any(text: str, *values: str) -> bool:
    normalized = (text or "").lower()
    return any((v or "").lower() in normalized for v in values)


def _strip_extension(file_name: str) -> str:
    if "." in file_name:
        return file_name.rsplit(".", 1)[0]
    return file_name


async def get_document_profile(db: AsyncSession, doc_id: str) -> DocumentProfile | None:
    from app.db.models.document import Document as DocModel
    from app.db.models.document import DocumentProfile as DocProfile

    stmt = (
        select(DocProfile)
        .join(DocModel, DocModel.id == DocProfile.document_id)
        .where(DocModel.doc_id == doc_id)
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


_SECTION_CODE_PATTERN = re.compile(
    r"^(第[一二三四五六七八九十百\d]+[章节条部分]\s*)|(\d+(?:\.\d+)+\s*)"
)
