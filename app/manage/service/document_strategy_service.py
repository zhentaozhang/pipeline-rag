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
    doc_internal_id = doc_row[0]
    content_quality_level = doc_row[1] or 0
    file_type = doc_row[2] or ""
    char_count = doc_row[3] or 0

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


async def build_chunks(db: AsyncSession, doc_id: str, text: str, task_id: str) -> list[dict]:
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

    from app.document.chunker import ChunkConfig, ChunkPipeline, ChunkStrategyType

    if not child_strategies:
        child_strategies = [ChunkStrategyType.STRUCTURE, ChunkStrategyType.RECURSIVE]

    parent_pipeline = ChunkPipeline(strategies=parent_strategies, config=ChunkConfig())
    child_pipeline = ChunkPipeline(strategies=child_strategies, config=ChunkConfig())

    parent_chunks = await parent_pipeline.run(text, doc_id) if parent_strategies else []
    child_chunks = await child_pipeline.run(text, doc_id)

    if parent_chunks:
        for p in parent_chunks:
            pb = DocumentParentBlock(
                id=int(p.chunk_id) if p.chunk_id.isdigit() else next_id(),
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
                child_count=sum(1 for c in child_chunks if c.parent_chunk_id == p.chunk_id),
            )
            db.add(pb)
        await db.flush()
        logger.info("parent blocks saved", count=len(parent_chunks), doc_id=doc_id)

    import dataclasses

    for c in child_chunks:
        c.document_id = doc_internal_id or 0

    return [dataclasses.asdict(c) for c in child_chunks]


def _map_strategy_type(type_code: int):
    from app.document.chunker import ChunkStrategyType

    mapping = {
        STRATEGY_STRUCTURE: ChunkStrategyType.STRUCTURE,
        STRATEGY_RECURSIVE: ChunkStrategyType.RECURSIVE,
        STRATEGY_SEMANTIC: ChunkStrategyType.SEMANTIC,
        STRATEGY_LLM: ChunkStrategyType.LLM,
    }
    return mapping.get(type_code)
