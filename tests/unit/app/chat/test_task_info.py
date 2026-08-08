"""ChatTaskInfo / ChatRuntimeRegistry 单元测试：CAS 语义、取消、注册表（纯内存，无 DB/LLM）。"""

import pytest

from app.chat.state_machine import ConversationState
from app.chat.task_info import ChatRuntimeRegistry, ChatTaskInfo


@pytest.fixture(autouse=True)
def _clean_registry():
    ChatRuntimeRegistry._registry.clear()
    yield
    ChatRuntimeRegistry._registry.clear()


class TestChatTaskInfo:
    def test_defaults(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        assert task.conv_state == ConversationState.INITIALIZED
        assert task.finalized is False
        assert task.cancelled is False
        assert task.total_tokens == 0
        assert task.model_name == "unknown"

    def test_finalize_cas_runs_once(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        assert task.finalize() is True
        assert task.finalized is True
        assert task.finalize() is False

    def test_add_token_usage_accumulates(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        task.add_token_usage(10, 20)
        task.add_token_usage(5, 5)
        assert task.prompt_tokens == 15
        assert task.completion_tokens == 25
        assert task.total_tokens == 40

    def test_try_set_first_response_time_cas(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        assert task.try_set_first_response_time(100) is True
        assert task.first_response_time_ms == 100
        assert task.try_set_first_response_time(999) is False
        assert task.first_response_time_ms == 100

    def test_cancel_sets_flag_and_event(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        task.cancel()
        assert task.cancelled is True
        assert task.cancel_event.is_set()

    def test_state_transitions_through_sm(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        task.sm.transition(ConversationState.EXECUTING)
        assert task.conv_state == ConversationState.EXECUTING


class TestChatRuntimeRegistry:
    def test_register_get_unregister(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        assert ChatRuntimeRegistry.register(task) is True
        assert ChatRuntimeRegistry.get("c1") is task
        assert ChatRuntimeRegistry.is_running("c1") is True
        ChatRuntimeRegistry.unregister("c1", task)
        assert ChatRuntimeRegistry.get("c1") is None
        assert ChatRuntimeRegistry.is_running("c1") is False

    def test_duplicate_register_rejected(self):
        t1 = ChatTaskInfo(conversation_id="c1", question="q1")
        t2 = ChatTaskInfo(conversation_id="c1", question="q2")
        assert ChatRuntimeRegistry.register(t1) is True
        assert ChatRuntimeRegistry.register(t2) is False
        assert ChatRuntimeRegistry.get("c1") is t1

    def test_unregister_with_wrong_task_is_noop(self):
        task = ChatTaskInfo(conversation_id="c1", question="q")
        other = ChatTaskInfo(conversation_id="c1", question="other")
        ChatRuntimeRegistry.register(task)
        ChatRuntimeRegistry.unregister("c1", other)
        assert ChatRuntimeRegistry.get("c1") is task

    def test_replace_cancels_old_task(self):
        t1 = ChatTaskInfo(conversation_id="c1", question="q1")
        t2 = ChatTaskInfo(conversation_id="c1", question="q2")
        ChatRuntimeRegistry.register(t1)
        assert ChatRuntimeRegistry.replace(t2) is True
        assert t1.cancelled is True
        assert ChatRuntimeRegistry.get("c1") is t2

    def test_cancel_returns_true_only_for_registered(self):
        assert ChatRuntimeRegistry.cancel("missing") is False
        task = ChatTaskInfo(conversation_id="c1", question="q")
        ChatRuntimeRegistry.register(task)
        assert ChatRuntimeRegistry.cancel("c1") is True
        assert task.cancelled is True

    def test_active_count(self):
        assert ChatRuntimeRegistry.active_count() == 0
        ChatRuntimeRegistry.register(ChatTaskInfo(conversation_id="c1", question="q"))
        ChatRuntimeRegistry.register(ChatTaskInfo(conversation_id="c2", question="q"))
        assert ChatRuntimeRegistry.active_count() == 2
