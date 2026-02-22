"""
Celery 异步任务定义 — 文档处理流水线

任务链：parse → chunk → vectorize → index → profile（每步独立日志+状态追踪）
"""

import structlog

logger = structlog.get_logger(__name__)

# ── Worker 进程共享事件循环 ────────────────────────────────────────────────
# Celery prefork 每个子进程一个事件循环，只 stop 不 close，保证连接池中的
# aiomysql/asyncpg 连接始终绑定到同一个循环，避免 "Future attached to a
# different loop" 错误。
import contextlib

from celery.signals import worker_process_init

from app.celery_app import _ensure_worker_loop, run_async
from app.common.enums import (
    DocumentLogLevelEnum,
    DocumentOperatorTypeEnum,
    DocumentParseStatusEnum,
    DocumentPipelineStageEnum,
    DocumentTaskEventTypeEnum,
    DocumentTaskStageEnum,
    DocumentTaskStatusEnum,
)


# ── Worker 子进程初始化（fork 之后执行）────────────────────────────────────
@worker_process_init.connect
def _on_worker_process_init(**kwargs) -> None:
    """在每个 prefork 子进程启动时初始化共享事件循环 + 所有基础设施。

    必须在子进程中执行（不能用模块级 import 代码），因为父进程 import 模块后
    fork，子进程继承的事件循环 selector fd 无效 → OSError: Bad file descriptor。
    worker_process_init 信号在 fork 之后触发，此时子进程的内存是干净的。
    """
    from app.db.session import _session_factory as mysql_factory
    from app.db.session import init_db
    from app.infra.es import _es as es_client
    from app.infra.es import init_es
    from app.infra.minio import init_minio
    from app.infra.pg import async_session_maker as pg_factory
    from app.infra.pg import init_pg

    _ensure_worker_loop()
    if mysql_factory is None:
        run_async(init_db())
    if pg_factory is None:
        run_async(init_pg())
    if es_client is None:
        run_async(init_es())
    # MinIO 客户端是同步的，在子进程中也需要重新初始化
    init_minio()


def _save_log(
    doc_id: str,
    task_id: str,
    stage_type: int,
    event_type: int,
    log_level: int,
    operator_type: int,
    operator_id: str,
    content: str,
    detail: dict | None,
) -> None:
    """同步封装 save_log — 将外部 doc_id 解析为内部 document_id"""

    async def _do():
        from sqlalchemy import select

        from app.db.models.document import Document as DocModel
        from app.manage.service.document_async_service import save_log

        async with _get_mysql_session() as db:
            # doc_id 是外部字符串 ID，需要解析为内部整数 document_id
            row = await db.execute(select(DocModel.id).where(DocModel.doc_id == doc_id))
            internal_id = row.scalar_one_or_none()
            doc_int = internal_id if internal_id is not None else 0
            await save_log(
                db,
                task_id,
                doc_int,
                stage_type,
                event_type,
                log_level,
                operator_type,
                operator_id,
                content,
                detail,
            )
            await db.commit()

    run_async(_do())


def _get_mysql_session():
    """获取 MySQL async session（pool 已在模块加载时初始化）"""
    from app.db.session import _session_factory

    if _session_factory is None:
        raise RuntimeError("MySQL session factory not initialized. Call init_db() first.")
    return _session_factory()


def _record_task(doc_id: str, stage: str, task_id: str, status: int = 1) -> None:
    async def _do():
        from app.manage.service.document_async_service import record_task

        async with _get_mysql_session() as db:
            await record_task(db, doc_id, stage, task_id, status)
            await db.commit()

    run_async(_do())


def _task_failed(task_self, doc_id: str, stage: int, fail_message: str, exc: Exception) -> None:
    """Celery 任务失败通用处理：日志 + 补偿清理 + 状态更新 + 重试"""
    with contextlib.suppress(Exception):
        _save_log(
            doc_id,
            task_self.request.id,
            stage,
            DocumentTaskEventTypeEnum.FAILED.value,
            DocumentLogLevelEnum.ERROR.value,
            DocumentOperatorTypeEnum.SYSTEM.value,
            "system",
            fail_message,
            {"error": str(exc)},
        )
    with contextlib.suppress(Exception):
        _compensate(doc_id, stage)
    with contextlib.suppress(Exception):
        _update_task_status(task_self.request.id, DocumentTaskStatusEnum.FAILED.value, str(exc))
    task_self.retry(exc=exc)


def _update_task_status(task_id: str, status: int, error_msg: str | None = None) -> None:
    async def _do():
        from app.manage.service.document_async_service import update_status

        async with _get_mysql_session() as db:
            await update_status(db, task_id, status, error_msg)
            await db.commit()

    run_async(_do())


# ── 流水线阶段追踪 ──────────────────────────────────────────────────────────


def _update_pipeline_stage(doc_id: str, stage: int) -> None:
    async def _do():
        from sqlalchemy import update

        from app.db.models.document import Document as DocModel

        async with _get_mysql_session() as db, db.begin():
            await db.execute(
                update(DocModel).where(DocModel.doc_id == doc_id).values(pipeline_stage=stage)
            )

    run_async(_do())


# ── 补偿清理 ─────────────────────────────────────────────────────────────────


TASK_STAGE_MAP: dict[str, int | None] = {
    "document.parse": DocumentTaskStageEnum.CONTENT_PARSE.value,
    "document.chunk": DocumentTaskStageEnum.CHUNK_EXECUTE.value,
    "document.vectorize": DocumentTaskStageEnum.VECTORIZE.value,
    "document.index": DocumentTaskStageEnum.STORE_COMPLETE.value,
    "document.profile": None,
}


def _infer_stage(task_name: str) -> int | None:
    return TASK_STAGE_MAP.get(task_name)


def _previous_stage(stage: int) -> int:
    mapping = {
        DocumentTaskStageEnum.CONTENT_PARSE.value: DocumentPipelineStageEnum.INIT.value,
        DocumentTaskStageEnum.CHUNK_EXECUTE.value: DocumentPipelineStageEnum.PARSED.value,
        DocumentTaskStageEnum.VECTORIZE.value: DocumentPipelineStageEnum.CHUNKED.value,
        DocumentTaskStageEnum.STORE_COMPLETE.value: DocumentPipelineStageEnum.VECTORIZED.value,
    }
    return mapping.get(stage, DocumentPipelineStageEnum.INIT.value)


def _update_document_failed(doc_id: str, error_msg: str) -> None:
    async def _do():
        from sqlalchemy import update

        from app.db.models.document import Document as DocModel

        async with _get_mysql_session() as db, db.begin():
            await db.execute(
                update(DocModel)
                .where(DocModel.doc_id == doc_id)
                .values(
                    parse_status=DocumentParseStatusEnum.PARSE_FAILED.value,
                    pipeline_stage=DocumentPipelineStageEnum.FAILED.value,
                    parse_error_msg=error_msg,
                )
            )

    run_async(_do())


def _compensate(doc_id: str, failed_stage: int | None) -> None:
    """补偿清理：清除失败步骤及后续步骤的残留数据"""
    if failed_stage is None:
        return

    async def _do():
        from sqlalchemy import delete, select

        from app.db.models.document import Document, DocumentChunk

        # vectorize 及之后 → 删 MySQL chunks + PG 向量
        if failed_stage >= DocumentTaskStageEnum.VECTORIZE.value:
            async with _get_mysql_session() as db, db.begin():
                doc = (
                    await db.execute(select(Document).where(Document.doc_id == doc_id))
                ).scalar_one_or_none()
                if doc:
                    await db.execute(
                        delete(DocumentChunk).where(DocumentChunk.document_id == doc.id)
                    )

            from app.infra.pg import close_pg, init_pg
            from app.infra.pg import transaction as _pg_transaction

            await init_pg()
            try:
                async with _pg_transaction() as conn, _get_mysql_session() as db:
                    doc = (
                        await db.execute(select(Document).where(Document.doc_id == doc_id))
                    ).scalar_one_or_none()
                    if doc:
                        await conn.execute(
                            "DELETE FROM pipeline_rag_document_embedding WHERE document_id = $1",
                            doc.id,
                        )
                        await conn.execute(
                            "DELETE FROM document_chunk WHERE doc_id = $1",
                            doc_id,
                        )
            finally:
                await close_pg()

        # index 及之后 → 删 ES + Neo4j
        if failed_stage >= DocumentTaskStageEnum.STORE_COMPLETE.value:
            from app.common.utils import safe_int
            from app.infra.es import close_es, get_es, init_es

            await init_es()
            try:
                es = get_es()
                doc_id_int = safe_int(doc_id, default=0)
                if doc_id_int:
                    await es.delete_by_query(
                        index="document_chunk",
                        body={"query": {"term": {"documentId": doc_id_int}}},
                        refresh=True,
                    )
            finally:
                await close_es()

            from app.config import get_settings

            if get_settings().neo4j.enabled:
                from app.infra.neo4j import close_neo4j, get_neo4j, init_neo4j

                await init_neo4j()
                try:
                    async with _get_mysql_session() as db:
                        doc = (
                            await db.execute(select(Document).where(Document.doc_id == doc_id))
                        ).scalar_one_or_none()
                        if doc:
                            driver = get_neo4j()
                            async with driver.session() as session:
                                await session.run(
                                    "MATCH (n:DocumentNode {documentId: $doc_id}) DETACH DELETE n",
                                    doc_id=doc.id,
                                )
                finally:
                    await close_neo4j()

        # 回退 pipeline_stage
        async with _get_mysql_session() as db, db.begin():
            from sqlalchemy import update as sa_update

            await db.execute(
                sa_update(Document)
                .where(Document.doc_id == doc_id)
                .values(pipeline_stage=_previous_stage(failed_stage))
            )

    run_async(_do())
