"""
API 路由聚合层
聚合 chat / admin_auth / manage 三组路由
"""

from fastapi.routing import APIRouter

# ── 路由聚合 ──────────────────────────────────────────────────────────────────
from app.api.admin_auth import router as auth_router
from app.api.chat_session import router as chat_session_router
from app.api.chat_session_exchange import router as chat_session_exchange_router
from app.api.chat_session_gap import router as chat_session_gap_router
from app.api.chat_stream import router as chat_stream_router
from app.api.manage_document import router as manage_document_router
from app.api.manage_document_chunk import router as manage_document_chunk_router
from app.api.manage_document_strategy import router as manage_document_strategy_router
from app.api.manage_document_structure import router as manage_document_structure_router
from app.api.manage_graph import router as manage_graph_router
from app.api.manage_knowledge_ops import router as manage_knowledge_ops_router
from app.api.manage_knowledge_scope import router as manage_knowledge_scope_router
from app.api.manage_metrics import router as manage_metrics_router
from app.api.manage_observability import router as manage_observability_router

api_router = APIRouter()
api_router.include_router(chat_stream_router, prefix="/api/chat", tags=["chat"])
api_router.include_router(chat_session_router, prefix="/api/chat", tags=["chat"])
api_router.include_router(chat_session_exchange_router, prefix="/api/chat", tags=["chat"])
api_router.include_router(chat_session_gap_router, prefix="/api/chat", tags=["chat"])
api_router.include_router(auth_router, prefix="/admin/auth", tags=["auth"])
api_router.include_router(manage_document_router, prefix="/manage", tags=["manage"])
api_router.include_router(manage_document_chunk_router, prefix="/manage", tags=["manage"])
api_router.include_router(manage_document_strategy_router, prefix="/manage", tags=["manage"])
api_router.include_router(manage_document_structure_router, prefix="/manage", tags=["manage"])
api_router.include_router(manage_graph_router, prefix="/manage", tags=["manage"])
api_router.include_router(manage_knowledge_ops_router, prefix="/manage", tags=["manage"])
api_router.include_router(manage_knowledge_scope_router, prefix="/manage", tags=["manage"])
api_router.include_router(manage_observability_router, prefix="/manage", tags=["manage"])
api_router.include_router(manage_metrics_router, prefix="/manage", tags=["manage-metrics"])
