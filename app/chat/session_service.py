"""
会话管理业务逻辑

对应 app/api/chat_session.py 中 6 个会话管理端点的业务逻辑。
"""

import json
from typing import Any

import structlog
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.chat_schema import ConversationSessionVO, SessionDetailVO, SessionPageResponse
from app.api.schemas.chat_session import SessionListRequest
from app.chat.store import ConversationArchiveStore
from app.chat.task_info import ChatRuntimeRegistry
from app.common.enums import ChatTurnStatus

logger = structlog.get_logger(__name__)


def _camel_case_keys(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return d
    keys = list(d.keys())
    for k in keys:
        parts = k.split("_")
        camel = parts[0] + "".join(p.capitalize() for p in parts[1:]) if "_" in k else k
        if camel != k:
            d[camel] = d.pop(k)
    for v in d.values():
        if isinstance(v, dict):
            _camel_case_keys(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    _camel_case_keys(item)
    return d


def _parse_turn_status(raw: str | None) -> int | None:
    if not raw or raw.upper() == "ALL":
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return ChatTurnStatus[raw.upper()].value
    except (KeyError, AttributeError):
        return None


async def stop_session(cid: str) -> dict[str, Any]:
    task = ChatRuntimeRegistry.get(cid)
    if not task:
        return {"conversationId": cid, "stopped": False, "message": "没有找到正在执行的会话"}

    if not task.finalize():
        return {"conversationId": cid, "stopped": False, "message": "会话已经结束"}

    current_task = ChatRuntimeRegistry.get(cid)
    if current_task is not task:
        return {"conversationId": cid, "stopped": False, "message": "会话已由新的执行接管"}

    task.cancel()
    return {"conversationId": cid, "stopped": True, "message": "已停止会话生成"}


async def get_session_detail(db: AsyncSession, cid: str) -> dict[str, Any] | None:
    from app.db.models.conversation import ConversationExchange, ConversationMemory
    from app.db.models.langgraph import GraphCheckpoint

    archive_store = ConversationArchiveStore(db)
    session = await archive_store.get_session(cid)
    if not session:
        return None

    stmt_mem = select(ConversationMemory).where(ConversationMemory.conversation_id == cid)
    memory = (await db.execute(stmt_mem)).scalar_one_or_none()

    exchange_count = (
        await db.execute(select(func.count()).where(ConversationExchange.conversation_id == cid))
    ).scalar() or 0

    try:
        checkpoint_count = (
            await db.execute(select(func.count()).where(GraphCheckpoint.thread_id == cid))
        ).scalar() or 0
    except Exception:
        checkpoint_count = 0

    latest_ex = (
        await db.execute(
            select(ConversationExchange)
            .where(ConversationExchange.conversation_id == cid)
            .order_by(desc(ConversationExchange.id))
            .limit(1)
        )
    ).scalar_one_or_none()

    is_running = ChatRuntimeRegistry.is_running(cid)
    task = ChatRuntimeRegistry.get(cid) if is_running else None

    latest_user_msg = latest_ex.question if latest_ex and latest_ex.question else ""
    latest_assistant_msg = latest_ex.answer if latest_ex and latest_ex.answer else ""
    if task and task.answer_buffer:
        live_answer = "".join(task.answer_buffer)
        if live_answer:
            latest_assistant_msg = live_answer

    exchange_rows, _ = await archive_store.list_exchanges(cid, page=1, size=200)
    exchange_dicts = []
    for ex in exchange_rows:
        try:
            steps = json.loads(ex.thinking_steps) if ex.thinking_steps else []
        except (json.JSONDecodeError, TypeError):
            steps = []
        try:
            refs = json.loads(ex.references) if ex.references else []
        except (json.JSONDecodeError, TypeError):
            refs = []
        try:
            recs = json.loads(ex.recommendations) if ex.recommendations else []
        except (json.JSONDecodeError, TypeError):
            recs = []
        try:
            ex_debug_trace = json.loads(ex.debug_trace_json) if ex.debug_trace_json else None
        except (json.JSONDecodeError, TypeError):
            ex_debug_trace = None
        exchange_dicts.append(
            {
                "exchangeId": str(ex.id),
                "question": ex.question or "",
                "answer": ex.answer or "",
                "thinkingSteps": steps,
                "references": refs,
                "recommendations": recs,
                "status": str(ex.status or ""),
                "errorMessage": ex.error_message or "",
                "createdAt": ex.created_at.isoformat() if ex.created_at else None,
                "updatedAt": ex.updated_at.isoformat() if ex.updated_at else None,
                "tokensUsed": ex.tokens_used,
                "totalResponseTimeMs": ex.total_response_time_ms,
                "executionMode": ex.execution_mode
                or (
                    ex_debug_trace.get("execution_mode") or ex_debug_trace.get("executionMode", "")
                    if ex_debug_trace
                    else ""
                ),
                "debugTrace": _camel_case_keys(ex_debug_trace),
            }
        )

    vo = SessionDetailVO(
        id=session.id,
        conversation_id=session.conversation_id,
        title=session.title or "",
        memory_summary=(memory.summary_text or "") if memory else "",
        created_at=session.created_at.isoformat() if session.created_at else None,
        updated_at=session.updated_at.isoformat() if session.updated_at else None,
        chat_mode=session.chat_mode or "auto",
        checkpoint_count=checkpoint_count,
        exchange_count=exchange_count,
        running=is_running,
        message_count=exchange_count * 2,
        latest_user_message=latest_user_msg,
        latest_assistant_message=latest_assistant_msg,
        latest_exchange_id=str(latest_ex.id) if latest_ex else None,
        latest_turn_status=ChatTurnStatus(latest_ex.turn_status).name
        if latest_ex and latest_ex.turn_status in (1, 2, 3, 4)
        else "UNKNOWN",
        latest_turn_error_message=latest_ex.error_message
        if latest_ex and latest_ex.error_message
        else "",
        exchanges=exchange_dicts,
    )

    return vo.model_dump(by_alias=True)


async def reset_session(db: AsyncSession, cid: str) -> dict[str, Any]:
    from app.chat.checkpoint_manager import ChatCheckpointManager
    from app.db.models.conversation import ConversationSession

    stopped_running_task = False
    task = ChatRuntimeRegistry.get(cid)
    if task:
        task.cancel()
        stopped_running_task = True

    await db.execute(
        update(ConversationSession)
        .where(ConversationSession.conversation_id == cid)
        .values(is_deleted=True, updated_at=func.now())
    )

    checkpoint_mgr = ChatCheckpointManager(db)
    removed_checkpoint_count = await checkpoint_mgr.clear_thread(cid)

    await db.commit()

    if task:
        ChatRuntimeRegistry.unregister(cid, task)

    return {
        "conversationId": cid,
        "stoppedRunningTask": stopped_running_task,
        "removedCheckpointCount": removed_checkpoint_count,
        "message": "会话已删除",
    }


async def _update_session_field(db: AsyncSession, cid: str, **values: Any) -> None:
    from app.db.models.conversation import ConversationSession

    await db.execute(
        update(ConversationSession)
        .where(ConversationSession.conversation_id == cid)
        .values(**values, updated_at=func.now())
    )
    await db.commit()


async def rename_session(db: AsyncSession, cid: str, title: str) -> dict[str, Any]:
    await _update_session_field(db, cid, title=title)
    return {"conversationId": cid, "title": title}


async def recover_session(db: AsyncSession, cid: str) -> dict[str, Any]:
    await _update_session_field(db, cid, is_deleted=False)
    return {"conversationId": cid, "message": "会话已恢复"}


async def pin_session(db: AsyncSession, cid: str, pinned: bool) -> dict[str, Any]:
    await _update_session_field(db, cid, is_pinned=pinned, pinned_at=func.now() if pinned else None)
    return {"conversationId": cid, "pinned": pinned}


async def list_sessions(db: AsyncSession, req: SessionListRequest) -> dict[str, Any]:
    from app.db.models.conversation import ConversationExchange, ConversationMemory

    archive_store = ConversationArchiveStore(db)
    sessions, total = await archive_store.list_sessions(
        page=req.page_no,
        size=req.page_size,
        keyword=req.keyword,
        chat_mode=req.chat_mode,
        turn_status=_parse_turn_status(req.turn_status),
    )

    cids = [s.conversation_id for s in sessions]
    exchange_counts: dict[str, int] = {}
    memory_map: dict[str, str] = {}
    latest_questions: dict[str, str] = {}
    latest_answers: dict[str, str] = {}
    latest_statuses: dict[str, str] = {}
    latest_error_messages: dict[str, str] = {}
    latest_exchange_ids: dict[str, int] = {}

    if cids:
        count_rows = (
            await db.execute(
                select(
                    ConversationExchange.conversation_id,
                    func.count(ConversationExchange.id).label("cnt"),
                )
                .where(ConversationExchange.conversation_id.in_(cids))
                .group_by(ConversationExchange.conversation_id)
            )
        ).all()
        exchange_counts = {row[0]: row[1] for row in count_rows}

        mem_rows = (
            await db.execute(
                select(ConversationMemory.conversation_id, ConversationMemory.summary_text).where(
                    ConversationMemory.conversation_id.in_(cids)
                )
            )
        ).all()
        memory_map = {row[0]: row[1] or "" for row in mem_rows}

        subq = (
            select(
                ConversationExchange.conversation_id,
                func.max(ConversationExchange.id).label("max_id"),
            )
            .where(ConversationExchange.conversation_id.in_(cids))
            .group_by(ConversationExchange.conversation_id)
        ).subquery()
        latest_ex_stmt = select(
            ConversationExchange.conversation_id,
            ConversationExchange.question,
            ConversationExchange.answer,
            ConversationExchange.id,
            ConversationExchange.turn_status,
            ConversationExchange.error_message,
        ).join(subq, ConversationExchange.id == subq.c.max_id)
        latest_exes = (await db.execute(latest_ex_stmt)).all()
        for row in latest_exes:
            cid = row[0]
            if row[1]:
                latest_questions[cid] = row[1]
            if row[2]:
                latest_answers[cid] = row[2]
            latest_exchange_ids[cid] = row[3]
            latest_statuses[cid] = (
                ChatTurnStatus(row[4]).name if row[4] in (1, 2, 3, 4) else "UNKNOWN"
            )
            if row[5]:
                latest_error_messages[cid] = row[5]

    vo_list = []
    for s in sessions:
        cid = s.conversation_id
        vo = ConversationSessionVO(
            id=s.id,
            conversation_id=cid,
            title=s.title or "",
            created_at=s.created_at.isoformat() if s.created_at else None,
            updated_at=s.updated_at.isoformat() if s.updated_at else None,
            chat_mode=s.chat_mode or "auto",
            exchange_count=exchange_counts.get(cid, 0),
            memory_summary=memory_map.get(cid, ""),
            running=ChatRuntimeRegistry.is_running(cid),
            message_count=exchange_counts.get(cid, 0) * 2,
            latest_user_message=latest_questions.get(cid, ""),
            latest_assistant_message=latest_answers.get(cid, ""),
            latest_exchange_id=str(latest_exchange_ids[cid])
            if cid in latest_exchange_ids
            else None,
            latest_turn_status=latest_statuses.get(cid, ""),
            latest_turn_error_message=latest_error_messages.get(cid, ""),
        )
        vo_list.append(vo)

    total_pages = 0 if total <= 0 else (total + req.page_size - 1) // req.page_size
    resp = SessionPageResponse(
        sessions=vo_list,
        total=total or 0,
        page_no=req.page_no,
        page_size=req.page_size,
        total_pages=total_pages,
    )
    return resp.model_dump(by_alias=True)
