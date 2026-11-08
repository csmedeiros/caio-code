"""Domain events: what the agent did, in the order it happened.

The TUI subscribes to these to render, the ledger subscribes to account for
tokens, and the eval harness subscribes to count compactions. Publishing an
event is how a use case reports progress without knowing who is listening.

Every event carries its instant, injected by the caller: the domain never reads
a clock.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from caio_code.domain.policy.base import PipelineDecision, PolicyDecision
from caio_code.domain.todo.items import TodoBoard
from caio_code.domain.usage.accounting import Cost, TokenUsage


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Base of every event."""

    at: datetime


@dataclass(frozen=True, slots=True)
class RunStarted(DomainEvent):
    run_id: str
    task: str
    model: str
    policy: str


@dataclass(frozen=True, slots=True)
class MessageAppended(DomainEvent):
    run_id: str
    message_id: str
    role: str
    chars: int
    preview: str


@dataclass(frozen=True, slots=True)
class ToolCallIssued(DomainEvent):
    run_id: str
    tool: str
    arguments: str
    call_id: str


@dataclass(frozen=True, slots=True)
class ToolCallCompleted(DomainEvent):
    run_id: str
    tool: str
    call_id: str
    chars: int
    truncated: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ContextShaped(DomainEvent):
    """A policy (or a pipeline of them) produced a decision."""

    run_id: str
    decision: PipelineDecision | PolicyDecision

    @property
    def record(self) -> dict[str, Any]:
        return self.decision.as_record()


@dataclass(frozen=True, slots=True)
class CompactionStarted(DomainEvent):
    run_id: str
    head_chars: int
    previous_summary: bool
    reason: str = "auto"


@dataclass(frozen=True, slots=True)
class CompactionEnded(DomainEvent):
    run_id: str
    summary_chars: int
    sections: int
    well_formed: bool
    usage: TokenUsage
    cost: Cost
    latency_ms: int
    reason: str = "auto"


@dataclass(frozen=True, slots=True)
class TodoBoardUpdated(DomainEvent):
    run_id: str
    board: TodoBoard


@dataclass(frozen=True, slots=True)
class GuardrailFired(DomainEvent):
    run_id: str
    guardrail: str
    detail: str


@dataclass(frozen=True, slots=True)
class UsageRecorded(DomainEvent):
    run_id: str
    usage: TokenUsage
    cost: Cost
    model: str
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class RunFinished(DomainEvent):
    run_id: str
    status: str
    usage: TokenUsage
    cost: Cost
    compactions: int
    error: str | None = None


@runtime_checkable
class EventBus(Protocol):
    """Publishes events to whoever subscribed."""

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> None:
        """Register a handler. Handlers must not raise into the publisher."""

    def publish(self, event: DomainEvent) -> None:
        """Deliver one event to every handler, in subscription order."""


@dataclass(slots=True)
class InMemoryEventBus:
    """The default bus: a list of handlers, synchronous delivery.

    A handler that raises is recorded and re-raised after the others ran, so one
    broken subscriber cannot hide an event from the ledger.
    """

    handlers: list[Callable[[DomainEvent], None]] = field(default_factory=list)
    failures: list[tuple[str, Exception]] = field(default_factory=list)

    def subscribe(self, handler: Callable[[DomainEvent], None]) -> None:
        self.handlers.append(handler)

    def publish(self, event: DomainEvent) -> None:
        errors: list[tuple[str, Exception]] = []
        for handler in self.handlers:
            try:
                handler(event)
            except Exception as exc:
                errors.append((getattr(handler, "__qualname__", repr(handler)), exc))
        self.failures.extend(errors)
        if errors:
            names = ", ".join(name for name, _ in errors)
            raise EventDeliveryError(f"event handlers failed: {names}") from errors[0][1]

    def drain(self, events: Sequence[DomainEvent]) -> None:
        for event in events:
            self.publish(event)


class EventDeliveryError(Exception):
    """A subscriber raised while handling an event."""
