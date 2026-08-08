"""ConversationExecutor.execute_structured 测试：SSE 流提取 text 与 references。"""

from collections.abc import AsyncIterator

from app.chat.schema import ExecutionPlan
from app.chat.task_info import ChatTaskInfo
from app.common.enums import ExecutionMode
from app.common.sse import SSEEventType, sse_event
from app.executors.base import ConversationExecutor


class _StubExecutor(ConversationExecutor):
    mode = ExecutionMode.RAG_CHAT

    def __init__(self, task: ChatTaskInfo) -> None:
        self.task = task
        self._events: list[str] = []

    def with_events(self, events: list[str]) -> "_StubExecutor":
        self._events = events
        return self

    async def execute(self, plan: ExecutionPlan) -> AsyncIterator[str]:
        for e in self._events:
            yield e


def _text_event(content: str) -> str:
    return sse_event(SSEEventType.TEXT, content)


class TestExecuteStructured:
    async def test_extracts_text_events(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        ex = _StubExecutor(task).with_events(
            [_text_event("第一段"), _text_event("第二段")]
        )

        result = await ex.execute_structured(ExecutionPlan(
            mode=ExecutionMode.RAG_CHAT,
            original_question="q",
            rewritten_question="q",
        ))

        assert result.text == "第一段第二段"
        assert result.mode == ExecutionMode.RAG_CHAT

    async def test_ignores_non_text_events(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        ex = _StubExecutor(task).with_events(
            [sse_event(SSEEventType.THINKING, "思考中"), _text_event("正文")]
        )

        result = await ex.execute_structured(ExecutionPlan(
            mode=ExecutionMode.RAG_CHAT,
            original_question="q",
            rewritten_question="q",
        ))

        assert result.text == "正文"

    async def test_ignores_invalid_json_lines(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        ex = _StubExecutor(task).with_events(
            ["data: {invalid json", "not-sse", _text_event("好")]
        )

        result = await ex.execute_structured(ExecutionPlan(
            mode=ExecutionMode.RAG_CHAT,
            original_question="q",
            rewritten_question="q",
        ))

        assert result.text == "好"

    async def test_captures_references_from_task(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        task.references = [{"id": "r1"}, {"id": "r2"}]
        ex = _StubExecutor(task).with_events([_text_event("内容")])

        result = await ex.execute_structured(ExecutionPlan(
            mode=ExecutionMode.RAG_CHAT,
            original_question="q",
            rewritten_question="q",
        ))

        assert result.references == [{"id": "r1"}, {"id": "r2"}]

    async def test_empty_stream_returns_empty_result(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        ex = _StubExecutor(task).with_events([])

        result = await ex.execute_structured(ExecutionPlan(
            mode=ExecutionMode.RAG_CHAT,
            original_question="q",
            rewritten_question="q",
        ))

        assert result.text == ""
        assert result.references == []
