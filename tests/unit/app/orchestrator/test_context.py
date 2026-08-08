
from app.chat.memory import MemoryContext
from app.common.enums import ChatQueryMode
from app.orchestrator.context import PrepareContext


def make_ctx(**overrides):
    defaults = dict(
        question="问题",
        conversation_id="c1",
        memory_ctx=MemoryContext(),
        chat_mode=ChatQueryMode.AUTO_DOCUMENT,
    )
    defaults.update(overrides)
    return PrepareContext(**defaults)


class TestPrepareContext:
    def test_defaults(self):
        ctx = make_ctx()
        assert ctx.tenant_id == "default"
        assert ctx.exchange_id == 0
        assert ctx.rewritten_question == ""
        assert ctx.rewrite_sub_questions == []
        assert ctx.routed_document_id is None
        assert ctx.top_doc_ids == []
        assert ctx.navigation_decision is None
        assert ctx.execution_mode is not None
        assert ctx.retrieval_question == ""
        assert ctx.retrieval_sub_questions == []

    def test_custom_tenant(self):
        ctx = make_ctx(tenant_id="t9")
        assert ctx.tenant_id == "t9"

    def test_time_sensitive_fields(self):
        ctx = make_ctx(requires_fresh_search=True, is_time_sensitive=True, current_date_text="2026-08-08")
        assert ctx.requires_fresh_search is True
        assert ctx.is_time_sensitive is True
        assert ctx.current_date_text == "2026-08-08"
