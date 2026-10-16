"""
两阶段文档切块策略服务
实现系统推荐 -> 人工确认的完整闭环。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.id_generator import next_id

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# Status codes for strategy types and roles
STRATEGY_STRUCTURE = 1
STRATEGY_RECURSIVE = 2
STRATEGY_SEMANTIC = 3
STRATEGY_LLM = 4

ROLE_PRIMARY = 1
ROLE_FALLBACK = 2
ROLE_OPTIMIZE = 3
ROLE_ENHANCE = 4

PIPELINE_PARENT = "parent"
PIPELINE_CHILD = "child"

SOURCE_SYSTEM_RECOMMEND = 1
SOURCE_USER_ADD = 2
SOURCE_USER_KEEP = 3

EXECUTE_WAIT = 0
PLAN_STATUS_PENDING = 1
PLAN_STATUS_CONFIRMED = 2


async def get_next_plan_version(db: AsyncSession, doc_id: str) -> int:
    from app.db.models.document import DocumentStrategyPlan

    """获取下一个 plan_version"""
    from app.db.models.document import Document

    doc = (await db.execute(select(Document).where(Document.doc_id == doc_id))).scalar_one_or_none()
    doc_internal_id = doc.id if doc else None
    if not doc_internal_id:
        return 1
    stmt = (
        select(DocumentStrategyPlan.plan_version)
        .where(DocumentStrategyPlan.document_id == doc_internal_id)
        .order_by(DocumentStrategyPlan.plan_version.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    latest = result.scalar_one_or_none()
    return (latest or 0) + 1


async def recommend_strategy(db: AsyncSession, doc_id: str) -> None:
    from app.db.models.document import DocumentStrategyPlan, DocumentStrategyStep

    """
    AI (或启发式) 推荐适合该文档的切块策略。
     生成 PARENT 和 CHILD 双管道步骤，包含主策略 + 优化/兜底/增强策略。
     不删除已有方案（版本递增）。
    """
    logger.info("recommending strategy for document", doc_id=doc_id)

    from sqlalchemy import func

    from app.db.models.document import Document, DocumentStructureNode

    doc_stmt = select(
        Document.id, Document.content_quality_level, Document.file_type, Document.char_count
    )
    doc_stmt = doc_stmt.where(Document.doc_id == doc_id)
    doc_res = await db.execute(doc_stmt)
    doc_row = doc_res.first()
    if not doc_row:
        logger.error("document not found for strategy recommendation", doc_id=doc_id)
        raise ValueError(f"document not found: {doc_id}")
    from app.common.utils import safe_int

    doc_internal_id = doc_row[0]
    content_quality_level = safe_int(doc_row[1], default=0)
    file_type = safe_int(doc_row[2], default=0)
    char_count = safe_int(doc_row[3], default=0)

    stmt = select(
        func.count(DocumentStructureNode.id), func.max(DocumentStructureNode.depth)
    ).where(DocumentStructureNode.document_id == doc_internal_id)
    res = await db.execute(stmt)
    row = res.first()
    heading_count = row[0] if row else 0
    max_depth = row[1] if row and row[1] is not None else 0

    # structure recommended when file type supports it and either structureLevel >= MEDIUM or headingCount >= 2
    structure_suitable_file_types = {1, 2, 3, 5, 6}  # PDF, DOC, DOCX, MD, HTML
    has_structure = file_type in structure_suitable_file_types and (
        heading_count >= 2 or (max_depth or 0) >= 2
    )

    reason_list = []
    plan_id = next_id()
    plan_version = await get_next_plan_version(db, doc_id)
    steps = []
    step_no = 1

    # ── Parent pipeline ──
    if has_structure:
        steps.append(
            DocumentStrategyStep(
                id=next_id(),
                plan_id=plan_id,
                document_id=doc_internal_id,
                step_no=step_no,
                pipeline_type=PIPELINE_PARENT,
                strategy_type=STRATEGY_STRUCTURE,
                strategy_role=ROLE_PRIMARY,
                source_type=SOURCE_SYSTEM_RECOMMEND,
                execute_status=EXECUTE_WAIT,
                recommend_reason="检测到文档具有较明显的标题或章节结构，父块优先保留天然章节边界。",
            )
        )
        step_no += 1
        reason_list.append("父块流水线优先采用基于文档结构切块，保留回答阶段需要的大语义单元。")
    else:
        steps.append(
            DocumentStrategyStep(
                id=next_id(),
                plan_id=plan_id,
                document_id=doc_internal_id,
                step_no=step_no,
                pipeline_type=PIPELINE_PARENT,
                strategy_type=STRATEGY_RECURSIVE,
                strategy_role=ROLE_PRIMARY,
                source_type=SOURCE_SYSTEM_RECOMMEND,
                execute_status=EXECUTE_WAIT,
                recommend_reason="未识别出稳定结构时，父块先使用较大粒度的递归分块作为稳定回答单元。",
            )
        )
        step_no += 1
        reason_list.append("父块流水线未命中明显结构信号，默认使用较大粒度递归分块作为回答单元。")

    # ── Child pipeline (primary + fallback) ──
    # contentQualityLevel: 3=HIGH, 2=MEDIUM, 1=LOW
    llm_recommended = content_quality_level == 1 and char_count >= 500
    semantic_recommended = not llm_recommended and char_count >= 1000 and heading_count >= 2

    children_added = 0
    if llm_recommended:
        steps.append(
            DocumentStrategyStep(
                id=next_id(),
                plan_id=plan_id,
                document_id=doc_internal_id,
                step_no=step_no,
                pipeline_type=PIPELINE_CHILD,
                strategy_type=STRATEGY_LLM,
                strategy_role=ROLE_PRIMARY,
                source_type=SOURCE_SYSTEM_RECOMMEND,
                execute_status=EXECUTE_WAIT,
                recommend_reason="文档质量偏低或结构识别不稳定，子块先使用大模型智能切块增强复杂场景。",
            )
        )
        step_no += 1
        children_added += 1
        reason_list.append("子块流水线追加大模型智能切块，处理低质量或结构不稳定文本。")
    elif semantic_recommended:
        steps.append(
            DocumentStrategyStep(
                id=next_id(),
                plan_id=plan_id,
                document_id=doc_internal_id,
                step_no=step_no,
                pipeline_type=PIPELINE_CHILD,
                strategy_type=STRATEGY_SEMANTIC,
                strategy_role=ROLE_PRIMARY,
                source_type=SOURCE_SYSTEM_RECOMMEND,
                execute_status=EXECUTE_WAIT,
                recommend_reason="文本主题边界相对明确，子块先使用语义分块优化召回边界。",
            )
        )
        step_no += 1
        children_added += 1
        reason_list.append("子块流水线优先采用语义分块，优化召回边界和主题完整性。")

    # Always add recursive fallback in child pipeline
    steps.append(
        DocumentStrategyStep(
            id=next_id(),
            plan_id=plan_id,
            document_id=doc_internal_id,
            step_no=step_no,
            pipeline_type=PIPELINE_CHILD,
            strategy_type=STRATEGY_RECURSIVE,
            strategy_role=ROLE_FALLBACK,
            source_type=SOURCE_SYSTEM_RECOMMEND,
            execute_status=EXECUTE_WAIT,
            recommend_reason="文档整体较长、存在超长段落，或需要在增强切块后追加长度兜底。",
        )
    )
    step_no += 1
    children_added += 1
    reason_list.append("子块流水线追加递归分块，控制召回单元长度并作为兜底。")

    # ── Build strategy snapshot ──────────────────────────────────────────────
    parent_step_types = [str(s.strategy_type) for s in steps if s.pipeline_type == PIPELINE_PARENT]
    child_step_types = [str(s.strategy_type) for s in steps if s.pipeline_type == PIPELINE_CHILD]
    strategy_snapshot = f"PARENT:{','.join(parent_step_types)};CHILD:{','.join(child_step_types)}"

    plan = DocumentStrategyPlan(
        id=plan_id,
        document_id=doc_internal_id,
        plan_version=plan_version,
        plan_source=1,
        plan_status=PLAN_STATUS_PENDING,
        strategy_count=len(steps),
        strategy_snapshot=strategy_snapshot,
        recommend_reason="；".join(reason_list),
        confirm_user_id=None,
        confirm_time=None,
    )
    db.add(plan)
    db.add_all(steps)
    await db.flush()
    logger.info("strategy recommended", doc_id=doc_id, plan_id=plan_id, snapshot=strategy_snapshot)


async def query_strategy_plan(db: AsyncSession, doc_id: str) -> dict | None:
    from app.db.models.document import Document, DocumentStrategyPlan, DocumentStrategyStep

    doc = (
        await db.execute(select(Document.id).where(Document.doc_id == doc_id))
    ).scalar_one_or_none()
    if not doc:
        return None
    doc_internal_id = doc

    stmt = (
        select(DocumentStrategyPlan)
        .where(DocumentStrategyPlan.document_id == doc_internal_id)
        .order_by(DocumentStrategyPlan.id.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    plan = res.scalar_one_or_none()
    if not plan:
        return None

    stmt_steps = (
        select(DocumentStrategyStep)
        .where(DocumentStrategyStep.plan_id == plan.id)
        .order_by(DocumentStrategyStep.step_no)
    )
    res_steps = await db.execute(stmt_steps)
    steps = res_steps.scalars().all()

    all_steps = [
        {
            "id": str(s.id),
            "step_no": s.step_no,
            "strategy_type": s.strategy_type,
            "strategy_role": s.strategy_role,
            "pipeline_type": (s.pipeline_type or "").upper(),
            "recommend_reason": s.recommend_reason,
        }
        for s in steps
    ]

    return {
        "plan": {
            "id": str(plan.id),
            "planId": str(plan.id),
            "plan_status": plan.plan_status,
            "strategy_snapshot": plan.strategy_snapshot,
            "recommend_reason": plan.recommend_reason,
        },
        "steps": all_steps,
        "parent_steps": [s for s in all_steps if s["pipeline_type"] == "PARENT"],
        "child_steps": [s for s in all_steps if s["pipeline_type"] != "PARENT"],
    }


async def normalize_steps(
    db: AsyncSession,
    doc_id: str,
    plan_id: int,
    request_parent_strategy_types: list[int],
    request_child_strategy_types: list[int],
) -> list[dict]:
    from app.db.models.document import DocumentStrategyStep

    """规范化步骤——用户调整后重新生成步骤"""
    from app.db.models.document import Document

    doc = (
        await db.execute(select(Document.id).where(Document.doc_id == doc_id))
    ).scalar_one_or_none()
    doc_internal_id = doc if doc else 0

    stmt_steps = (
        select(DocumentStrategyStep)
        .where(
            DocumentStrategyStep.plan_id == plan_id,
            DocumentStrategyStep.document_id == doc_internal_id,
        )
        .order_by(DocumentStrategyStep.step_no)
    )
    res = await db.execute(stmt_steps)
    base_steps = res.scalars().all()

    valid_types = {STRATEGY_STRUCTURE, STRATEGY_RECURSIVE, STRATEGY_SEMANTIC, STRATEGY_LLM}
    parent_types = [t for t in request_parent_strategy_types if t in valid_types]
    child_types = [t for t in request_child_strategy_types if t in valid_types]

    parent_map = {
        s.strategy_type: s for s in base_steps if (s.pipeline_type or "").upper() == "PARENT"
    }
    child_map = {
        s.strategy_type: s for s in base_steps if (s.pipeline_type or "").upper() == "CHILD"
    }

    new_steps = []
    step_no = 1

    for idx, strategy_type in enumerate(parent_types):
        base = parent_map.get(strategy_type)
        role = (
            ROLE_PRIMARY
            if idx == 0
            else (ROLE_FALLBACK if strategy_type == STRATEGY_RECURSIVE else ROLE_OPTIMIZE)
        )
        new_steps.append(
            DocumentStrategyStep(
                id=next_id(),
                plan_id=plan_id,
                document_id=doc_internal_id,
                step_no=step_no,
                pipeline_type=PIPELINE_PARENT,
                strategy_type=strategy_type,
                strategy_role=role,
                source_type=SOURCE_USER_KEEP if base else SOURCE_USER_ADD,
                execute_status=EXECUTE_WAIT,
                recommend_reason=base.recommend_reason if base else "用户手动追加该策略。",
            )
        )
        step_no += 1

    for idx, strategy_type in enumerate(child_types):
        base = child_map.get(strategy_type)
        role = (
            ROLE_PRIMARY
            if idx == 0
            else (ROLE_FALLBACK if strategy_type == STRATEGY_RECURSIVE else ROLE_OPTIMIZE)
        )
        new_steps.append(
            DocumentStrategyStep(
                id=next_id(),
                plan_id=plan_id,
                document_id=doc_internal_id,
                step_no=step_no,
                pipeline_type=PIPELINE_CHILD,
                strategy_type=strategy_type,
                strategy_role=role,
                source_type=SOURCE_USER_KEEP if base else SOURCE_USER_ADD,
                execute_status=EXECUTE_WAIT,
                recommend_reason=base.recommend_reason if base else "用户手动追加该策略。",
            )
        )
        step_no += 1

    await db.execute(delete(DocumentStrategyStep).where(DocumentStrategyStep.plan_id == plan_id))
    db.add_all(new_steps)
    await db.flush()

    return [
        {
            "step_no": s.step_no,
            "strategy_type": s.strategy_type,
            "strategy_role": s.strategy_role,
            "pipeline_type": s.pipeline_type,
        }
        for s in new_steps
    ]


async def confirm_strategy(db: AsyncSession, doc_id: str, plan_id: int, user_id: int) -> None:
    from app.db.models.document import DocumentStrategyPlan

    """人工确认策略计划，触发最终生效"""
    from app.common.enums import DocumentStrategyStatusEnum
    from app.db.models.document import Document

    doc = (await db.execute(select(Document).where(Document.doc_id == doc_id))).scalar_one_or_none()
    doc_internal_id = doc.id if doc else None

    stmt = select(DocumentStrategyPlan).where(
        DocumentStrategyPlan.id == plan_id, DocumentStrategyPlan.document_id == doc_internal_id
    )
    res = await db.execute(stmt)
    plan = res.scalar_one_or_none()
    if not plan:
        raise ValueError("Plan not found")

    plan.plan_status = PLAN_STATUS_CONFIRMED
    plan.confirm_user_id = user_id
    plan.confirm_time = datetime.now()

    if doc:
        doc.strategy_status = DocumentStrategyStatusEnum.CONFIRMED.value
        doc.current_plan_id = plan_id

    await db.flush()
    logger.info("strategy confirmed", doc_id=doc_id, plan_id=plan_id)


async def build_chunks(db: AsyncSession, doc_id: str, text: str, task_id: str = "0") -> list[dict]:
    from app.db.models.document import DocumentStrategyPlan, DocumentStrategyStep

    """批量构建 Parent-Child 切块关联关系"""
    from app.db.models.document import Document, DocumentParentBlock

    doc = (await db.execute(select(Document).where(Document.doc_id == doc_id))).scalar_one_or_none()
    doc_internal_id = doc.id if doc else None

    stmt = (
        select(DocumentStrategyPlan)
        .where(
            DocumentStrategyPlan.document_id == doc_internal_id,
            DocumentStrategyPlan.plan_status == PLAN_STATUS_CONFIRMED,
        )
        .order_by(DocumentStrategyPlan.id.desc())
        .limit(1)
    )
    res = await db.execute(stmt)
    plan = res.scalar_one_or_none()

    parent_strategies = []
    child_strategies = []
    plan_id = None
    if plan:
        plan_id = plan.id
        stmt_steps = (
            select(DocumentStrategyStep)
            .where(DocumentStrategyStep.plan_id == plan.id)
            .order_by(DocumentStrategyStep.step_no)
        )
        res_steps = await db.execute(stmt_steps)
        steps = res_steps.scalars().all()
        for step in steps:
            strategy_type = _map_strategy_type(step.strategy_type)
            if step.pipeline_type and step.pipeline_type.upper() == "PARENT":
                if strategy_type:
                    parent_strategies.append(strategy_type)
            else:
                if strategy_type:
                    child_strategies.append(strategy_type)

    from app.document.chunker import (
        Chunk,
        ChunkConfig,
        ChunkPipeline,
        ChunkStrategyType,
        LLMChunker,
        RecursiveChunker,
        SemanticChunker,
        StructureChunker,
    )

    if not child_strategies:
        child_strategies = [ChunkStrategyType.RECURSIVE]

    parent_chunks: list[Chunk] = []
    child_chunks: list[Chunk] = []

    # 1. 执行父块策略 (Parent Strategy)
    if parent_strategies:
        if ChunkStrategyType.STRUCTURE in parent_strategies:
            parent_chunks = await StructureChunker().chunk(text, doc_id, ChunkConfig())
        elif ChunkStrategyType.RECURSIVE in parent_strategies:
            parent_chunks = await RecursiveChunker().chunk(
                text, doc_id, ChunkConfig(chunk_size=1500, min_chunk_size=100)
            )

        for p in parent_chunks:
            p.chunk_type = "parent"
            p.document_id = doc_internal_id or 0
            p.plan_id = plan_id

    # 2. 执行子块策略 (Child Strategy)，与父块建立严格的关联引用
    if parent_chunks:
        if ChunkStrategyType.LLM in child_strategies:
            for p in parent_chunks:
                p_children = await LLMChunker().chunk(p.content, doc_id, ChunkConfig())
                for c in p_children:
                    c.parent_chunk_id = p.chunk_id
                    c.section_title = p.section_title
                    c.section_path = p.section_path
                    c.structure_node_id = p.structure_node_id
                    c.structure_node_type = p.structure_node_type
                    c.canonical_path = p.canonical_path
                child_chunks.extend(p_children)
        elif ChunkStrategyType.RECURSIVE in child_strategies or not child_strategies:
            child_chunks = await RecursiveChunker().chunk_parents(parent_chunks, ChunkConfig())
        else:
            child_chunks = await RecursiveChunker().chunk_parents(
                parent_chunks, ChunkConfig(chunk_size=999999)
            )

        if ChunkStrategyType.SEMANTIC in child_strategies and child_chunks:
            child_chunks = await SemanticChunker().chunk(child_chunks, ChunkConfig())
    else:
        child_pipeline = ChunkPipeline(strategies=child_strategies, config=ChunkConfig())
        child_chunks = await child_pipeline.run(text, doc_id)

    for idx, c in enumerate(child_chunks):
        c.chunk_type = "child"
        c.chunk_index = idx
        c.document_id = doc_internal_id or 0
        c.plan_id = plan_id

    # 3. 幂等保存父块至 MySQL DocumentParentBlock (先删旧，再插新)
    if doc_internal_id:
        await db.execute(
            delete(DocumentParentBlock).where(DocumentParentBlock.document_id == doc_internal_id)
        )

    if parent_chunks:
        from app.common.utils import stable_id_to_int

        for p in parent_chunks:
            matched_children = [c for c in child_chunks if c.parent_chunk_id == p.chunk_id]
            start_no = min((c.chunk_index for c in matched_children), default=None)
            end_no = max((c.chunk_index for c in matched_children), default=None)
            pb = DocumentParentBlock(
                id=stable_id_to_int(p.chunk_id),
                document_id=doc_internal_id,
                task_id=task_id,
                plan_id=plan_id,
                parent_no=p.chunk_index,
                source_type=1,
                section_path=p.section_path,
                structure_node_id=p.structure_node_id,
                structure_node_type=p.structure_node_type,
                canonical_path=p.canonical_path,
                item_index=None,
                parent_text=p.content,
                char_count=len(p.content),
                token_count=p.token_count,
                child_count=len(matched_children),
                start_chunk_no=start_no,
                end_chunk_no=end_no,
            )
            db.add(pb)
        await db.flush()
        logger.info(
            "parent blocks saved",
            count=len(parent_chunks),
            doc_id=doc_id,
            children_linked=len(child_chunks),
        )

    import dataclasses

    # 返回父块与子块的合集，使下游 VectorizerService 和 PGVector document_chunk 能够完整落盘
    all_chunks = parent_chunks + child_chunks
    return [dataclasses.asdict(c) for c in all_chunks]


def _map_strategy_type(type_code: int):
    from app.document.chunker import ChunkStrategyType

    mapping = {
        STRATEGY_STRUCTURE: ChunkStrategyType.STRUCTURE,
        STRATEGY_RECURSIVE: ChunkStrategyType.RECURSIVE,
        STRATEGY_SEMANTIC: ChunkStrategyType.SEMANTIC,
        STRATEGY_LLM: ChunkStrategyType.LLM,
    }
    return mapping.get(type_code)
