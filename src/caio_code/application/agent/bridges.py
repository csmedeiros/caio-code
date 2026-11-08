"""Bridges to the concurrently-written application modules.

Five collaborators are being written in parallel with this package:

- ``caio_code.application.compaction.service.CompactionService``
- ``caio_code.application.metrics.ledger.RunLedger``
- ``caio_code.application.todos.service.TodoTracker``
- ``caio_code.application.guardrails.repeated_tool_call.RepeatedToolCallGuard``
- ``caio_code.infrastructure.middleware.context_policy.ContextPolicyMiddleware``

Every import here is lazy (inside a function) and falls back to a minimal,
offline, deterministic implementation of the documented contract when the real
module is not on disk yet. The fallbacks exist so this package imports, runs
and tests green today; the moment the real modules land they take over
unchanged, because the loaders prefer them.

The Protocols below are the contract this package codes against. They are
structural, so both the real classes and the fallbacks satisfy them.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
from langchain_core.messages import AnyMessage

from caio_code.config import GuardrailConfig
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Transcript
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.events import (
    CompactionEnded,
    ContextShaped,
    DomainEvent,
    EventBus,
    GuardrailFired,
    ToolCallCompleted,
    UsageRecorded,
)
from caio_code.domain.policy.base import PipelineDecision, PolicyPipeline, PolicyRequest
from caio_code.domain.ports.time import Clock, IdentifierFactory
from caio_code.domain.ports.tokenizer import TokenCounter
from caio_code.domain.todo.items import TodoBoard, TodoItem, TodoStatus
from caio_code.domain.usage.accounting import PriceSheet, RunAccounting, UsageLedger
from caio_code.infrastructure.mappers.langchain import apply_pipeline, to_domain, to_langchain

SUMMARY_MESSAGE_ID = "compaction:summary"
GUARDRAIL_NAME = "repeated_tool_call"
FALLBACK_TODO_ID_TEMPLATE = "todo-{index:04d}"
EPOCH = datetime.fromtimestamp(0, tz=UTC)
"""Instant the clock-free fallback guard stamps its events with."""

ModelHandler = Callable[[ModelRequest[Any]], Any]
AsyncModelHandler = Callable[[ModelRequest[Any]], Awaitable[Any]]


# ---------------------------------------------------------------------------
# Structural contracts of the collaborator modules
# ---------------------------------------------------------------------------


@runtime_checkable
class RunLedgerPort(Protocol):
    """What ``application.metrics.ledger.RunLedger`` promises."""

    compactions: int
    truncated_tool_outputs: int

    def accounting(self) -> RunAccounting: ...
    def reset(self) -> None: ...


@runtime_checkable
class TodoTrackerPort(Protocol):
    """What ``application.todos.service.TodoTracker`` promises."""

    board: TodoBoard

    def replace_from_tool_arguments(self, raw_json: str, *, run_id: str) -> TodoBoard: ...
    def replace(self, items: Sequence[TodoItem], *, run_id: str) -> TodoBoard: ...


@dataclass(frozen=True, slots=True)
class FallbackGuardrailVerdict:
    """Verdict shape documented for ``RepeatedToolCallGuard.inspect``."""

    fired: bool
    message: str
    repeats: int


@runtime_checkable
class GuardPort(Protocol):
    """What ``RepeatedToolCallGuard`` promises: ``inspect`` returns a verdict."""

    def inspect(self, tool_name: str, arguments: str, *, run_id: str) -> Any:
        """Returns an object with ``fired: bool``, ``message: str``, ``repeats: int``."""


@runtime_checkable
class CompactionServicePort(Protocol):
    """What ``application.compaction.service.CompactionService`` promises."""

    async def compact(
        self,
        *,
        transcript: Transcript,
        request: PolicyRequest,
        decision: Any,
        run_id: str,
        reason: str = "auto",
    ) -> Any:
        """Returns a ``CompactionOutcome`` carrying ``.message`` among others."""


# ---------------------------------------------------------------------------
# Lazy loaders: prefer the real module, fall back to the offline double
# ---------------------------------------------------------------------------


def load_run_ledger_factory() -> type[Any]:
    """``RunLedger`` when present, else :class:`FallbackRunLedger`."""
    try:
        from caio_code.application.metrics.ledger import RunLedger
    except ImportError:
        return FallbackRunLedger
    return RunLedger


def load_todo_tracker_factory() -> type[Any]:
    """``TodoTracker`` when present, else :class:`FallbackTodoTracker`."""
    try:
        from caio_code.application.todos.service import TodoTracker
    except ImportError:
        return FallbackTodoTracker
    return TodoTracker


def load_guard_factory() -> type[Any]:
    """``RepeatedToolCallGuard`` when present, else :class:`FallbackRepeatedToolCallGuard`."""
    try:
        from caio_code.application.guardrails.repeated_tool_call import RepeatedToolCallGuard
    except ImportError:
        return FallbackRepeatedToolCallGuard
    return RepeatedToolCallGuard


def load_context_policy_middleware_factory() -> type[AgentMiddleware[Any, Any, Any]]:
    """``ContextPolicyMiddleware`` when present, else the fallback middleware."""
    try:
        from caio_code.infrastructure.middleware.context_policy import ContextPolicyMiddleware
    except ImportError:
        return FallbackContextPolicyMiddleware
    return ContextPolicyMiddleware


def load_compaction_service_class() -> type[CompactionServicePort] | None:
    """The ``CompactionService`` class when present, else ``None``."""
    try:
        from caio_code.application.compaction.service import CompactionService
    except ImportError:
        return None
    return CompactionService


# ---------------------------------------------------------------------------
# Offline fallbacks
# ---------------------------------------------------------------------------


class FallbackRunLedger:
    """Accumulates ``UsageRecorded`` events into a :class:`RunAccounting`.

    Mirrors the documented ``RunLedger(bus, pricing, model)`` contract: it
    subscribes itself to the bus, counts compactions and truncated tool
    outputs, and ``reset()`` clears everything for the next run.
    """

    def __init__(self, bus: EventBus, pricing: PriceSheet, model: str) -> None:
        self._ledger = UsageLedger(model=model)
        self._pricing = pricing
        self.compactions = 0
        self.truncated_tool_outputs = 0
        bus.subscribe(self._on_event)

    def _on_event(self, event: DomainEvent) -> None:
        match event:
            case UsageRecorded():
                cost = self._pricing.cost_of(event.usage, event.model)
                self._ledger.model = event.model
                self._ledger.record(event.usage, cost=cost)
            case CompactionEnded():
                self.compactions += 1
            case ToolCallCompleted() if event.truncated:
                self.truncated_tool_outputs += 1
            case _:
                pass

    def accounting(self) -> RunAccounting:
        return self._ledger.accounting()

    def reset(self) -> None:
        self._ledger = UsageLedger(model=self._ledger.model)
        self.compactions = 0
        self.truncated_tool_outputs = 0


class FallbackTodoTracker:
    """Replaces the whole board from ``write_todos`` arguments, as documented.

    Deliberately publishes nothing: the runner owns ``TodoBoardUpdated`` so
    the event is published exactly once whichever tracker implementation is
    active.
    """

    def __init__(self, bus: EventBus, clock: Clock, identifiers: IdentifierFactory) -> None:
        self._bus = bus
        self._clock = clock
        self._identifiers = identifiers
        self._board = TodoBoard()

    @property
    def board(self) -> TodoBoard:
        return self._board

    def replace_from_tool_arguments(self, raw_json: str, *, run_id: str) -> TodoBoard:
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            msg = f"write_todos arguments are not valid JSON: {raw_json[:80]!r}"
            raise ConfigurationError(msg) from exc
        entries = payload.get("todos") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            msg = f"write_todos arguments carry no todo list: {raw_json[:80]!r}"
            raise ConfigurationError(msg)
        items: list[TodoItem] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                msg = f"todo entry {index} is not an object: {entry!r}"
                raise ConfigurationError(msg)
            content = str(entry.get("content", "")).strip()
            if not content:
                continue
            items.append(
                TodoItem(
                    id=FALLBACK_TODO_ID_TEMPLATE.format(index=index + 1),
                    content=content,
                    status=_todo_status(entry.get("status"), index=index),
                    priority=str(entry.get("priority", "medium")),
                    order=index,
                )
            )
        return self.replace(items, run_id=run_id)

    def replace(self, items: Sequence[TodoItem], *, run_id: str) -> TodoBoard:
        self._board = self._board.replace(items)
        return self._board


def _todo_status(raw: Any, *, index: int) -> TodoStatus:
    value = str(raw if raw is not None else TodoStatus.PENDING.value)
    try:
        return TodoStatus(value)
    except ValueError as exc:
        msg = f"todo entry {index} has unknown status {value!r}"
        raise ConfigurationError(msg) from exc


class FallbackRepeatedToolCallGuard:
    """Loop detection: the same ``(tool, arguments)`` repeated ``max_repeats`` times.

    Fires from the ``max_repeats``-th identical call onwards, within a sliding
    history of ``window_messages`` inspected calls, and publishes
    ``GuardrailFired`` on the bus, as the real guard (which also takes the bus)
    does.
    """

    def __init__(self, config: GuardrailConfig, bus: EventBus) -> None:
        self._config = config
        self._bus = bus
        self._history: deque[tuple[str, str]] = deque(maxlen=config.window_messages)

    def inspect(self, tool_name: str, arguments: str, *, run_id: str) -> FallbackGuardrailVerdict:
        entry = (tool_name, arguments)
        repeats = sum(1 for seen in self._history if seen == entry) + 1
        self._history.append(entry)
        fired = repeats >= self._config.max_repeats
        message = (
            f"guardrail {GUARDRAIL_NAME}: {tool_name} called {repeats} times with identical "
            f"arguments {arguments[:80]!r}; stop repeating it and try a different approach"
        )
        if fired:
            self._bus.publish(
                GuardrailFired(at=EPOCH, run_id=run_id, guardrail=GUARDRAIL_NAME, detail=message)
            )
        return FallbackGuardrailVerdict(fired=fired, message=message, repeats=repeats)


class FallbackContextPolicyMiddleware(AgentMiddleware[Any, Any, Any]):
    """Reshapes ``request.messages`` through the pipeline on every model call.

    Mirrors the documented ``ContextPolicyMiddleware`` contract: publishes
    ``ContextShaped`` with the pipeline decision and, when a compaction
    service is supplied, replaces the compaction placeholder with the
    anchored summary before the model sees the messages (async path only; the
    sync path keeps the placeholder rather than blocking on model I/O).
    """

    def __init__(
        self,
        pipeline: PolicyPipeline,
        *,
        counter: TokenCounter,
        bus: EventBus,
        clock: Clock,
        compaction: CompactionServicePort | None = None,
        budget: TokenBudget,
        run_id: str = "",
    ) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._counter = counter
        self._bus = bus
        self._clock = clock
        self._compaction = compaction
        self._budget = budget
        self.run_id = run_id

    def _plan(self, request: ModelRequest[Any]) -> tuple[PipelineDecision, PolicyRequest]:
        transcript = Transcript.of(to_domain(message) for message in request.messages)
        policy_request = PolicyRequest(
            transcript=transcript,
            budget=self._budget,
            counter=self._counter,
        )
        decision = self._pipeline.plan(policy_request)
        self._bus.publish(
            ContextShaped(at=self._clock.now(), run_id=self.run_id, decision=decision)
        )
        return decision, policy_request

    def wrap_model_call(self, request: ModelRequest[Any], handler: ModelHandler) -> Any:
        decision, _ = self._plan(request)
        shaped = apply_pipeline(list(request.messages), decision)
        return handler(request.override(messages=shaped))

    async def awrap_model_call(
        self, request: ModelRequest[Any], handler: AsyncModelHandler
    ) -> Any:
        decision, policy_request = self._plan(request)
        shaped = apply_pipeline(list(request.messages), decision)
        shaped = await self._fill_summary(shaped, decision, policy_request)
        return await handler(request.override(messages=shaped))

    async def _fill_summary(
        self,
        shaped: list[AnyMessage],
        decision: PipelineDecision,
        policy_request: PolicyRequest,
    ) -> list[AnyMessage]:
        if self._compaction is None:
            return shaped
        if not any(getattr(message, "id", None) == SUMMARY_MESSAGE_ID for message in shaped):
            return shaped
        outcome = await self._compaction.compact(
            transcript=policy_request.transcript,
            request=policy_request,
            decision=decision.final,
            run_id=self.run_id,
            reason="auto",
        )
        summary_message = getattr(outcome, "message", None)
        if summary_message is None:
            return shaped
        replaced = to_langchain(summary_message)
        return [
            replaced if getattr(message, "id", None) == SUMMARY_MESSAGE_ID else message
            for message in shaped
        ]


__all__ = [
    "EPOCH",
    "CompactionServicePort",
    "FallbackContextPolicyMiddleware",
    "FallbackGuardrailVerdict",
    "FallbackRepeatedToolCallGuard",
    "FallbackRunLedger",
    "FallbackTodoTracker",
    "GuardPort",
    "RunLedgerPort",
    "TodoTrackerPort",
    "load_compaction_service_class",
    "load_context_policy_middleware_factory",
    "load_guard_factory",
    "load_run_ledger_factory",
    "load_todo_tracker_factory",
]
