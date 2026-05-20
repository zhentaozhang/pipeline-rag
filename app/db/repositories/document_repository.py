from __future__ import annotations

from typing import Any

from sqlalchemy import asc, delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import BusinessStatus
from app.db.models.document import (
    Document,
    DocumentChunk,
    DocumentParentBlock,
    DocumentProfile,
    DocumentStrategyPlan,
    DocumentStrategyStep,
    DocumentStructureNode,
    DocumentTask,
    PipelineRAGDocumentTask,
)
from app.db.models.task_log import DocumentTaskLog


class DocumentRepository:
    @staticmethod
    async def get_by_doc_id(db: AsyncSession, doc_id: str) -> Document | None:
        return await db.scalar(select(Document).where(Document.doc_id == doc_id))

    @staticmethod
    async def get_by_internal_id(db: AsyncSession, internal_id: int) -> Document | None:
        return await db.get(Document, internal_id)

    @staticmethod
    async def list_documents(
        db: AsyncSession,
        page: int,
        size: int,
        scope_code: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Document], int]:
        query = select(Document).where(Document.status == BusinessStatus.YES.value)
        if scope_code:
            query = query.where(Document.knowledge_scope_code == scope_code)
        if keyword:
            query = query.where(
                Document.document_name.ilike(f"%{keyword}%")
                | Document.original_file_name.ilike(f"%{keyword}%")
            )
        total = await db.scalar(select(func.count()).select_from(query.subquery()))
        stmt = (
            query.order_by(desc(Document.updated_at), desc(Document.id))
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(stmt)
        return result.scalars().all(), total or 0

    @staticmethod
    async def get_by_doc_ids(db: AsyncSession, doc_ids: list[str]) -> dict[str, Document]:
        if not doc_ids:
            return {}
        stmt = select(Document).where(Document.doc_id.in_(doc_ids))
        result: dict[str, Document] = {}
        for doc in (await db.execute(stmt)).scalars().all():
            result[doc.doc_id] = doc
        return result

    @staticmethod
    async def create(db: AsyncSession, **kwargs: Any) -> Document:
        doc = Document(**kwargs)
        db.add(doc)
        await db.flush()
        return doc

    @staticmethod
    async def delete_by_doc_id(db: AsyncSession, doc_id: str) -> None:
        await db.execute(delete(Document).where(Document.doc_id == doc_id))

    @staticmethod
    async def get_chunks_page(
        db: AsyncSession, doc_internal_id: int, page: int, size: int
    ) -> tuple[list[DocumentChunk], int]:
        query = select(DocumentChunk).where(DocumentChunk.document_id == doc_internal_id)
        total = await db.scalar(select(func.count()).select_from(query.subquery()))
        stmt = query.order_by(asc(DocumentChunk.chunk_no)).offset((page - 1) * size).limit(size)
        result = await db.execute(stmt)
        return result.scalars().all(), total or 0

    @staticmethod
    async def get_sibling_chunks(
        db: AsyncSession, parent_block_id: int, exclude_chunk_id: str
    ) -> list[DocumentChunk]:
        s_stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.parent_block_id == parent_block_id)
            .order_by(DocumentChunk.chunk_no)
        )
        s_res = await db.execute(s_stmt)
        return [sc for sc in s_res.scalars().all() if str(sc.id) != exclude_chunk_id]

    @staticmethod
    async def get_chunk_by_id(
        db: AsyncSession, chunk_id: int, doc_internal_id: int
    ) -> DocumentChunk | None:
        stmt = select(DocumentChunk).where(
            DocumentChunk.id == chunk_id, DocumentChunk.document_id == doc_internal_id
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def delete_chunks_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_internal_id))

    @staticmethod
    async def get_parent_blocks_by_ids(
        db: AsyncSession, ids: list[int]
    ) -> dict[int, DocumentParentBlock]:
        if not ids:
            return {}
        stmt = select(DocumentParentBlock).where(DocumentParentBlock.id.in_(ids))
        result: dict[int, DocumentParentBlock] = {}
        for pb in (await db.execute(stmt)).scalars().all():
            result[pb.id] = pb
        return result

    @staticmethod
    async def get_parent_block_by_id(
        db: AsyncSession, parent_block_id: int
    ) -> DocumentParentBlock | None:
        stmt = select(DocumentParentBlock).where(DocumentParentBlock.id == parent_block_id)
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def delete_parent_blocks_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(
            delete(DocumentParentBlock).where(DocumentParentBlock.document_id == doc_internal_id)
        )

    @staticmethod
    async def delete_structure_nodes_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(
            delete(DocumentStructureNode).where(
                DocumentStructureNode.document_id == doc_internal_id
            )
        )

    @staticmethod
    async def get_active_task_count(db: AsyncSession, doc_id: str) -> int:
        from app.common.enums import DocumentTaskStatusEnum

        active = await db.scalar(
            select(func.count()).select_from(
                select(DocumentTask)
                .where(
                    DocumentTask.doc_id == doc_id,
                    DocumentTask.status.in_(
                        [DocumentTaskStatusEnum.NEW.value, DocumentTaskStatusEnum.RUNNING.value]
                    ),
                )
                .subquery()
            )
        )
        return active or 0

    @staticmethod
    async def delete_tasks_by_doc_id(db: AsyncSession, doc_id: str) -> None:
        await db.execute(delete(DocumentTask).where(DocumentTask.doc_id == doc_id))

    @staticmethod
    async def delete_super_tasks_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(
            delete(PipelineRAGDocumentTask).where(
                PipelineRAGDocumentTask.document_id == doc_internal_id
            )
        )

    @staticmethod
    async def get_latest_task_by_doc_ids(
        db: AsyncSession, doc_ids: list[int]
    ) -> dict[int, PipelineRAGDocumentTask]:
        if not doc_ids:
            return {}
        stmt = (
            select(PipelineRAGDocumentTask)
            .where(PipelineRAGDocumentTask.document_id.in_(doc_ids))
            .order_by(PipelineRAGDocumentTask.id.desc())
        )
        result: dict[int, PipelineRAGDocumentTask] = {}
        for task in (await db.execute(stmt)).scalars().all():
            if task.document_id not in result:
                result[task.document_id] = task
        return result

    @staticmethod
    async def get_latest_task_by_doc_id(
        db: AsyncSession, doc_id: int
    ) -> PipelineRAGDocumentTask | None:
        stmt = (
            select(PipelineRAGDocumentTask)
            .where(PipelineRAGDocumentTask.document_id == doc_id)
            .order_by(PipelineRAGDocumentTask.id.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def delete_profile_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(
            delete(DocumentProfile).where(DocumentProfile.document_id == doc_internal_id)
        )

    @staticmethod
    async def get_strategy_plan_by_doc_id(
        db: AsyncSession, doc_id: str
    ) -> DocumentStrategyPlan | None:
        stmt = (
            select(DocumentStrategyPlan)
            .where(DocumentStrategyPlan.document_id == doc_id)
            .order_by(DocumentStrategyPlan.id.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def delete_strategy_steps_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(
            delete(DocumentStrategyStep).where(DocumentStrategyStep.document_id == doc_internal_id)
        )

    @staticmethod
    async def delete_strategy_plans_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(
            delete(DocumentStrategyPlan).where(DocumentStrategyPlan.document_id == doc_internal_id)
        )

    @staticmethod
    async def delete_task_logs_by_doc_id(db: AsyncSession, doc_internal_id: int) -> None:
        await db.execute(
            delete(DocumentTaskLog).where(DocumentTaskLog.document_id == doc_internal_id)
        )
