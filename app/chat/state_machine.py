"""
形式化对话状态机

定义 ConversationState 枚举和 ConversationStateMachine 类，
为对话生命周期提供显式状态转换、转换守卫和观测钩子。

用法:
    sm = ConversationStateMachine()
    sm.transition(ConversationState.LOCK_ACQUIRED)
    sm.assert_state(ConversationState.REGISTERED, ConversationState.PREPARED)
    print(sm.state)  # ConversationState.LOCK_ACQUIRED
    print(sm.elapsed_ms_in_state)  # int
    print(sm.transition_count)  # int
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import structlog

from app.eventbus.events import Event, StateTransitionPayload

logger = structlog.get_logger(__name__)


class ConversationState(StrEnum):
    INITIALIZED = "INITIALIZED"
    LOCK_ACQUIRED = "LOCK_ACQUIRED"
    REGISTERED = "REGISTERED"
    MEMORY_LOADED = "MEMORY_LOADED"
    ORCHESTRATING = "ORCHESTRATING"
    PREPARED = "PREPARED"
    EXECUTING = "EXECUTING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


_TRANSITIONS: dict[ConversationState, set[ConversationState]] = {
    ConversationState.INITIALIZED: {
        ConversationState.LOCK_ACQUIRED,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
    },
    ConversationState.LOCK_ACQUIRED: {
        ConversationState.REGISTERED,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
    },
    ConversationState.REGISTERED: {
        ConversationState.MEMORY_LOADED,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
    },
    ConversationState.MEMORY_LOADED: {
        ConversationState.ORCHESTRATING,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
    },
    ConversationState.ORCHESTRATING: {
        ConversationState.PREPARED,
        ConversationState.REJECTED,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
    },
    ConversationState.PREPARED: {
        ConversationState.EXECUTING,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
    },
    ConversationState.EXECUTING: {
        ConversationState.FINALIZING,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
    },
    ConversationState.FINALIZING: {
        ConversationState.COMPLETED,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
    },
    ConversationState.COMPLETED: set(),
    ConversationState.FAILED: set(),
    ConversationState.CANCELLED: set(),
    ConversationState.REJECTED: set(),
}

_TERMINAL_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.COMPLETED,
        ConversationState.FAILED,
        ConversationState.CANCELLED,
        ConversationState.REJECTED,
    }
)


class IllegalTransitionError(RuntimeError):
    pass


class ConversationStateMachine:
    def __init__(self, *, strict: bool = False) -> None:
        self._state: ConversationState = ConversationState.INITIALIZED
        self._strict = strict
        self._state_enter_time: float = time.monotonic()
        self._transition_count: int = 0
        self._entry_hooks: dict[ConversationState, list[Callable[..., None]]] = defaultdict(list)
        self._exit_hooks: dict[ConversationState, list[Callable[..., None]]] = defaultdict(list)
        self._global_hooks: list[Callable[..., None]] = []
        self._attach_default_hooks()

    # ── 状态属性 ────────────────────────────────────────────────────

    @property
    def state(self) -> ConversationState:
        return self._state

    # ── 钩子注册 ────────────────────────────────────────────────────

    def on_enter(self, state: ConversationState, hook: Callable) -> None:
        self._entry_hooks[state].append(hook)

    def on_exit(self, state: ConversationState, hook: Callable) -> None:
        self._exit_hooks[state].append(hook)

    def on_transition(self, hook: Callable) -> None:
        self._global_hooks.append(hook)

    # ── 核心 ────────────────────────────────────────────────────────

    def transition(
        self,
        target: ConversationState,
        *,
        strict: bool | None = None,
        **metadata: Any,
    ) -> ConversationState:
        strict = self._strict if strict is None else strict

        if target is self._state:
            return self._state

        if self._state in _TERMINAL_STATES:
            if strict:
                raise IllegalTransitionError(
                    f"Cannot transition from terminal state {self._state} -> {target}"
                )
            logger.warning(
                "state_machine.transition_from_terminal",
                current=self._state,
                target=target,
                **metadata,
            )
            return self._state

        allowed = _TRANSITIONS.get(self._state, set())
        if target not in allowed:
            if strict:
                raise IllegalTransitionError(
                    f"Invalid transition: {self._state} -> {target} "
                    f"(allowed: {', '.join(s.value for s in sorted(allowed))})"
                )
            logger.warning(
                "state_machine.invalid_transition",
                current=self._state,
                target=target,
                allowed=[s.value for s in sorted(allowed)],
                **metadata,
            )

        elapsed_ms = int((time.monotonic() - self._state_enter_time) * 1000)
        old_state = self._state

        for hook in self._exit_hooks.get(old_state, []):
            try:
                hook(old_state, target, elapsed_ms=elapsed_ms, **metadata)
            except Exception:
                logger.exception("state_machine.exit_hook_error", state=old_state)

        self._state = target
        self._state_enter_time = time.monotonic()
        self._transition_count += 1

        for hook in self._global_hooks:
            try:
                hook(old_state, target, elapsed_ms=elapsed_ms, **metadata)
            except Exception:
                logger.exception("state_machine.global_hook_error")

        for hook in self._entry_hooks.get(target, []):
            try:
                hook(old_state, target, elapsed_ms=elapsed_ms, **metadata)
            except Exception:
                logger.exception("state_machine.entry_hook_error", state=target)

        return self._state

    def _attach_default_hooks(self) -> None:
        self._global_hooks.append(_log_transition)
        self._global_hooks.append(_emit_eventbus_transition)


def _log_transition(
    old_state: ConversationState,
    new_state: ConversationState,
    elapsed_ms: int = 0,
    **kwargs: Any,
) -> None:
    logger.info(
        "conv.state",
        from_state=old_state,
        to_state=new_state,
        elapsed_ms=elapsed_ms,
        **kwargs,
    )


def _emit_eventbus_transition(
    old_state: ConversationState,
    new_state: ConversationState,
    elapsed_ms: int = 0,
    **kwargs: Any,
) -> None:
    try:
        import asyncio

        from app.eventbus.bus import bus

        event = Event(
            name="state.transition",
            payload=StateTransitionPayload(
                from_state=str(old_state),
                to_state=str(new_state),
                elapsed_ms=elapsed_ms,
                metadata=kwargs,
            ),
        )
        loop = asyncio.get_running_loop()
        loop.create_task(bus.emit(event))
    except RuntimeError:
        pass
    except Exception:
        logger.exception("eventbus._emit_transition_failed")
