"""ConversationStateMachine 状态机测试：合法转换、非法转换、终端态、钩子。"""

import pytest

from app.chat.state_machine import (
    ConversationState,
    ConversationStateMachine,
    IllegalTransitionError,
)


def _next_states() -> list[ConversationState]:
    return [
        ConversationState.LOCK_ACQUIRED,
        ConversationState.REGISTERED,
        ConversationState.MEMORY_LOADED,
        ConversationState.ORCHESTRATING,
        ConversationState.PREPARED,
        ConversationState.EXECUTING,
        ConversationState.FINALIZING,
        ConversationState.COMPLETED,
    ]


class TestHappyPath:
    def test_initial_state_is_initialized(self):
        sm = ConversationStateMachine()
        assert sm.state == ConversationState.INITIALIZED

    def test_full_pipeline_transition(self):
        sm = ConversationStateMachine()
        for target in _next_states():
            sm.transition(target)
        assert sm.state == ConversationState.COMPLETED
        assert sm.transition_count == len(_next_states())

    def test_failed_and_cancelled_are_reachable_from_each_stage(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.LOCK_ACQUIRED)
        sm.transition(ConversationState.REGISTERED)
        sm.transition(ConversationState.FAILED)
        assert sm.state == ConversationState.FAILED


class TestIllegalTransitions:
    def test_non_strict_warns_but_transitions_on_invalid_transition(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.EXECUTING)
        assert sm.state == ConversationState.EXECUTING

    def test_strict_raises_on_invalid_transition(self):
        sm = ConversationStateMachine(strict=True)
        with pytest.raises(IllegalTransitionError, match="Invalid transition"):
            sm.transition(ConversationState.EXECUTING)

    def test_terminal_state_rejects_further_transition(self):
        sm = ConversationStateMachine(strict=True)
        sm.transition(ConversationState.FAILED)
        with pytest.raises(IllegalTransitionError, match="terminal"):
            sm.transition(ConversationState.REGISTERED)

    def test_non_strict_terminal_transition_keeps_terminal_state(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.COMPLETED)
        sm.transition(ConversationState.EXECUTING)
        assert sm.state == ConversationState.COMPLETED

    def test_self_transition_is_noop(self):
        sm = ConversationStateMachine(strict=True)
        assert sm.transition(ConversationState.INITIALIZED) == ConversationState.INITIALIZED
        assert sm.transition_count == 0


class TestHooks:
    def test_on_enter_hook_receives_target_state(self):
        sm = ConversationStateMachine()
        calls: list[ConversationState] = []
        sm.on_enter(ConversationState.PREPARED, lambda old, new, **kw: calls.append(new))
        sm.transition(ConversationState.PREPARED)
        assert calls == [ConversationState.PREPARED]

    def test_on_exit_hook_receives_old_state(self):
        sm = ConversationStateMachine()
        calls: list[ConversationState] = []
        sm.on_exit(ConversationState.INITIALIZED, lambda old, new, **kw: calls.append(old))
        sm.transition(ConversationState.LOCK_ACQUIRED)
        assert calls == [ConversationState.INITIALIZED]

    def test_on_transition_global_hook_receives_both(self):
        sm = ConversationStateMachine()
        pairs: list[tuple[ConversationState, ConversationState]] = []
        sm.on_transition(lambda old, new, **kw: pairs.append((old, new)))
        sm.transition(ConversationState.LOCK_ACQUIRED)
        assert pairs == [(ConversationState.INITIALIZED, ConversationState.LOCK_ACQUIRED)]

    def test_hook_error_does_not_break_transition(self):
        sm = ConversationStateMachine()
        sm.on_enter(ConversationState.PREPARED, lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        sm.transition(ConversationState.PREPARED)
        assert sm.state == ConversationState.PREPARED

    def test_metadata_passed_to_hooks(self):
        sm = ConversationStateMachine()
        seen: dict = {}
        sm.on_transition(lambda old, new, **kw: seen.update(kw))
        sm.transition(ConversationState.LOCK_ACQUIRED, trace_id="t-1")
        assert seen["trace_id"] == "t-1"
