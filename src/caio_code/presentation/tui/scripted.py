"""ScriptedFacade: an offline, deterministic AgentFacade for tests and the driver.

A script is a tuple of typed steps. ``send(text)`` publishes ``RunStarted``,
the user message, then replays every step as domain events on the injected
bus, and finishes with ``RunFinished``. No model, no network, no wall-clock
sleep: the only await point between steps is an injected async sleep whose
default is ``asyncio.sleep(0)``, which yields to the event loop (so an
``interrupt()`` lands between steps) without advancing real time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.errors import CaioCodeError
from caio_code.domain.events import (
    CompactionEnded,
    CompactionStarted,
    ContextShaped,
    DomainEvent,
    EventBus,
    GuardrailFired,
    MessageAppended,
    RunFinished,
    RunStarted,
    TodoBoardUpdated,
    ToolCallCompleted,
    ToolCallIssued,
    UsageRecorded,
)
from caio_code.domain.policy.base import PolicyDecision, Removal
from caio_code.domain.ports.time import Clock, IdentifierFactory
from caio_code.domain.todo.items import TodoBoard, TodoItem, TodoStatus
from caio_code.domain.usage.accounting import (
    PriceSheet,
    RunAccounting,
    TokenUsage,
    UsageLedger,
)
from caio_code.presentation.tui.ports import (
    DEFAULT_MODEL,
    DEFAULT_POLICY,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_ERROR,
    RUN_STATUS_INTERRUPTED,
)

AsyncSleep = Callable[[float], Awaitable[None]]
YIELD_SECONDS = 0.0
COMPACTION_SECTIONS = 5
DEFAULT_DELTA_COUNT = 1
INTERRUPT_TIMEOUT_SECONDS = 5.0
""""Safety net so a missing interrupt cannot hang a scenario forever."""
ID_PREFIX_PAD = 4
FIXED_NOW_YEAR = 2026
SCRIPTED_ERROR_TEXT = "scripted error"
SUMMARY_ROLE = "summary"
DEMO_BUDGET_TOKENS = 8_000
"""Budget shown by the offline demo script; mirrors config.WindowConfig.tokens."""
DEMO_TOKENS_BEFORE = 6_400
DEMO_TOKENS_AFTER = 6_100


class ScriptedFacadeError(CaioCodeError):
    """The scripted facade was used in a way its contract forbids."""


class ScriptTokenCounter:
    """Minimal TokenCounter used to build scripted decisions.

    Counts are irrelevant to the TUI (the step carries the real numbers); the
    protocol instance is required by ``PolicyDecision``.
    """

    name = "script"

    def count_text(self, text: str) -> int:
        return len(text)

    def count_message(self, message: Message) -> int:
        return message.char_count()

    def count_messages(self, messages: Sequence[Message]) -> int:
        return sum(self.count_message(message) for message in messages)

    def count_transcript(self, transcript: Transcript) -> int:
        return self.count_messages(list(transcript))


@dataclass(frozen=True, slots=True)
class AssistantStep:
    """An assistant reply, published as ``deltas`` growing MessageAppended events."""

    text: str
    deltas: int = DEFAULT_DELTA_COUNT


@dataclass(frozen=True, slots=True)
class ToolStep:
    """One tool call with a canned result."""

    tool: str
    arguments: str
    result: str
    truncated: bool = False
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TodoStep:
    """A full board replacement: ``(content, status)`` pairs."""

    items: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ContextStep:
    """A context decision with the numbers a policy would have measured."""

    policy: str
    tokens_before: int
    tokens_after: int
    budget_tokens: int
    kept: int = 0
    dropped: int = 0
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompactionStep:
    """A compaction: start event, anchored summary message, end event."""

    summary_text: str
    head_chars: int = 0
    sections: int = COMPACTION_SECTIONS
    well_formed: bool = True
    reason: str = "auto"


@dataclass(frozen=True, slots=True)
class UsageStep:
    """One recorded model call."""

    usage: TokenUsage
    model: str = DEFAULT_MODEL


@dataclass(frozen=True, slots=True)
class GuardrailStep:
    """A guardrail firing."""

    guardrail: str
    detail: str


@dataclass(frozen=True, slots=True)
class AwaitInterruptStep:
    """Yield to the event loop until ``interrupt()`` lands, with a spin cap.

    Makes the interrupt scenario deterministic without pacing delays: the
    replay parks on an asyncio.Event that ``interrupt()`` sets, so pending key
    presses are processed while the run stays open. ``timeout_seconds`` is a
    hang guard only; a timeout continues the script and the scenario's
    assertions then fail loudly downstream.
    """

    timeout_seconds: float = INTERRUPT_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class FinishStep:
    """End the run with an explicit status (default: completed)."""

    status: str = RUN_STATUS_COMPLETED


ScriptStep = (
    AssistantStep
    | ToolStep
    | TodoStep
    | ContextStep
    | CompactionStep
    | UsageStep
    | GuardrailStep
    | AwaitInterruptStep
    | FinishStep
)
Script = tuple[ScriptStep, ...]


def split_deltas(text: str, parts: int) -> tuple[str, ...]:
    """Split ``text`` into ``parts`` growing prefixes, deterministically."""
    if parts < 1:
        msg = f"delta count must be positive, got {parts}"
        raise ScriptedFacadeError(msg)
    if not text:
        return (text,)
    chunk = -(-len(text) // parts)  # ceil division
    prefixes = []
    for end in range(chunk, len(text), chunk):
        prefixes.append(text[:end])
    prefixes.append(text)
    return tuple(prefixes)


def todo_board(entries: Sequence[tuple[str, str | TodoStatus]]) -> TodoBoard:
    """Build a board from ``(content, status)`` pairs with sequential ids."""
    items = [
        TodoItem(
            id=f"todo-{index + 1:0{ID_PREFIX_PAD}d}",
            content=content,
            status=TodoStatus(status),
            order=index,
        )
        for index, (content, status) in enumerate(entries)
    ]
    return TodoBoard.of(items)


def demo_script() -> Script:
    """The script replayed by ``--scenario demo``: a small but complete turn."""
    return (
        AssistantStep("I will inspect the repository and fix the bug.", deltas=3),
        ToolStep(
            tool="read_file",
            arguments='{"path": "src/caio_code/config.py"}',
            result="def load_settings(): ...",
        ),
        TodoStep(
            (
                ("Read the failing module", "completed"),
                ("Patch the window policy", "in_progress"),
                ("Run the tests", "pending"),
            )
        ),
        ContextStep(
            policy="sliding_window",
            tokens_before=DEMO_TOKENS_BEFORE,
            tokens_after=DEMO_TOKENS_AFTER,
            budget_tokens=DEMO_BUDGET_TOKENS,
            kept=12,
            dropped=2,
        ),
        UsageStep(usage=TokenUsage(input_tokens=6_100, output_tokens=220, cached_input_tokens=4_000)),
        AssistantStep("Patched the policy; tests are green.", deltas=2),
        FinishStep(),
    )


@dataclass
class ScriptedFacade:
    """Deterministic AgentFacade: replays a fixed script on every send."""

    bus: EventBus
    clock: Clock
    identifiers: IdentifierFactory
    script: Script = field(default_factory=tuple)
    model: str = DEFAULT_MODEL
    policy: str = DEFAULT_POLICY
    sleep: AsyncSleep = field(default=asyncio.sleep)
    price_sheet: PriceSheet = field(default_factory=PriceSheet)

    def __post_init__(self) -> None:
        self._run_id = ""
        self._board = TodoBoard()
        self._ledger = UsageLedger(model=self.model)
        self._context: dict[str, object] = {}
        self._interrupted = False
        self._interrupt_timeout = False
        self._interrupt_event = asyncio.Event()
        self._running = False
        self.shutdown_calls = 0
        self._compactions = 0
        self._finished = False
        self._events: list[DomainEvent] = []

    # ------------------------------------------------------------------
    # AgentFacade protocol
    # ------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def board(self) -> TodoBoard:
        return self._board

    @property
    def accounting(self) -> RunAccounting:
        return self._ledger.accounting()

    @property
    def context(self) -> dict[str, object]:
        return dict(self._context)

    @property
    def events(self) -> tuple[DomainEvent, ...]:
        """Everything published so far, for test assertions."""
        return tuple(self._events)

    def set_script(self, script: Script) -> None:
        self.script = tuple(script)

    async def send(self, text: str) -> None:
        if self._running:
            msg = "send() called while a scripted run is still replaying"
            raise ScriptedFacadeError(msg)
        self._running = True
        self._interrupted = False
        self._finished = False
        self._interrupt_event.clear()
        self._run_id = self.identifiers.run_id()
        try:
            self._publish(
                RunStarted(
                    at=self.clock.now(),
                    run_id=self._run_id,
                    task=text,
                    model=self.model,
                    policy=self.policy,
                )
            )
            user_id = self.identifiers.message_id()
            self._publish(
                MessageAppended(
                    at=self.clock.now(),
                    run_id=self._run_id,
                    message_id=user_id,
                    role=Role.USER,
                    chars=len(text),
                    preview=text,
                )
            )
            await self._replay()
        finally:
            self._running = False

    async def interrupt(self) -> None:
        self._interrupted = True
        self._interrupt_event.set()

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        self._running = False

    # ------------------------------------------------------------------
    # Replay
    # ------------------------------------------------------------------

    async def _replay(self) -> None:
        for step in self.script:
            await self.sleep(YIELD_SECONDS)
            if self._interrupted:
                self._finish(RUN_STATUS_INTERRUPTED)
                return
            await self._run_step(step)
            if self._interrupted:
                self._finish(RUN_STATUS_INTERRUPTED)
                return
        if not self._finished:
            self._finish(RUN_STATUS_INTERRUPTED if self._interrupted else RUN_STATUS_COMPLETED)

    async def _run_step(self, step: ScriptStep) -> None:
        match step:
            case AssistantStep():
                self._run_assistant(step)
            case ToolStep():
                self._run_tool(step)
            case TodoStep():
                self._run_todo(step)
            case ContextStep():
                self._run_context(step)
            case CompactionStep():
                self._run_compaction(step)
            case UsageStep():
                self._run_usage(step)
            case GuardrailStep():
                self._publish(
                    GuardrailFired(
                        at=self.clock.now(),
                        run_id=self._run_id,
                        guardrail=step.guardrail,
                        detail=step.detail,
                    )
                )
            case AwaitInterruptStep():
                await self._await_interrupt(step)
            case FinishStep():
                self._finish(step.status)
            case _:
                msg = f"unknown script step {type(step).__name__!r}"
                raise ScriptedFacadeError(msg)

    async def _await_interrupt(self, step: AwaitInterruptStep) -> None:
        try:
            await asyncio.wait_for(self._interrupt_event.wait(), timeout=step.timeout_seconds)
        except TimeoutError:
            self._interrupt_timeout = True

    def _run_assistant(self, step: AssistantStep) -> None:
        message_id = self.identifiers.message_id()
        for prefix in split_deltas(step.text, step.deltas):
            self._publish(
                MessageAppended(
                    at=self.clock.now(),
                    run_id=self._run_id,
                    message_id=message_id,
                    role=Role.ASSISTANT,
                    chars=len(prefix),
                    preview=prefix,
                )
            )

    def _run_tool(self, step: ToolStep) -> None:
        call_id = self.identifiers.message_id()
        self._publish(
            ToolCallIssued(
                at=self.clock.now(),
                run_id=self._run_id,
                tool=step.tool,
                arguments=step.arguments,
                call_id=call_id,
            )
        )
        if step.error is None:
            self._publish(
                MessageAppended(
                    at=self.clock.now(),
                    run_id=self._run_id,
                    message_id=call_id,
                    role=Role.TOOL,
                    chars=len(step.result),
                    preview=step.result,
                )
            )
        self._publish(
            ToolCallCompleted(
                at=self.clock.now(),
                run_id=self._run_id,
                tool=step.tool,
                call_id=call_id,
                chars=len(step.result),
                truncated=step.truncated,
                error=step.error,
            )
        )

    def _run_todo(self, step: TodoStep) -> None:
        self._board = todo_board(step.items)
        self._publish(
            TodoBoardUpdated(at=self.clock.now(), run_id=self._run_id, board=self._board)
        )

    def _run_context(self, step: ContextStep) -> None:
        counter = ScriptTokenCounter()
        removals = tuple(
            Removal(index=index, reason="scripted") for index in range(step.dropped)
        )
        decision = PolicyDecision(
            policy=step.policy,
            kept_indices=tuple(range(step.kept)),
            counter=counter,
            removals=removals,
            tokens_before=step.tokens_before,
            tokens_after=step.tokens_after,
            budget_tokens=step.budget_tokens,
            notes=step.notes,
        )
        self._context = decision.as_record()
        self._publish(
            ContextShaped(at=self.clock.now(), run_id=self._run_id, decision=decision)
        )

    def _run_compaction(self, step: CompactionStep) -> None:
        started_ms = self.clock.monotonic_ms()
        self._publish(
            CompactionStarted(
                at=self.clock.now(),
                run_id=self._run_id,
                head_chars=step.head_chars,
                previous_summary=False,
                reason=step.reason,
            )
        )
        summary_id = self.identifiers.message_id()
        self._publish(
            MessageAppended(
                at=self.clock.now(),
                run_id=self._run_id,
                message_id=summary_id,
                role=SUMMARY_ROLE,
                chars=len(step.summary_text),
                preview=step.summary_text,
            )
        )
        usage = TokenUsage()
        latency_ms = self.clock.monotonic_ms() - started_ms
        self._compactions += 1
        self._publish(
            CompactionEnded(
                at=self.clock.now(),
                run_id=self._run_id,
                summary_chars=len(step.summary_text),
                sections=step.sections,
                well_formed=step.well_formed,
                usage=usage,
                cost=self.price_sheet.cost_of(usage, self.model),
                latency_ms=latency_ms,
                reason=step.reason,
            )
        )

    def _run_usage(self, step: UsageStep) -> None:
        cost = self.price_sheet.cost_of(step.usage, step.model)
        self._ledger.record(step.usage, cost=cost)
        self._ledger.model = step.model
        self._publish(
            UsageRecorded(
                at=self.clock.now(),
                run_id=self._run_id,
                usage=step.usage,
                cost=cost,
                model=step.model,
            )
        )

    def _finish(self, status: str) -> None:
        if self._finished:
            return
        self._finished = True
        accounting = self._ledger.accounting()
        self._publish(
            RunFinished(
                at=self.clock.now(),
                run_id=self._run_id,
                status=status,
                usage=accounting.usage,
                cost=accounting.cost,
                compactions=self._compactions,
                error=None if status != RUN_STATUS_ERROR else SCRIPTED_ERROR_TEXT,
            )
        )

    def _publish(self, event: DomainEvent) -> None:
        self._events.append(event)
        self.bus.publish(event)


def fixed_now(year: int = FIXED_NOW_YEAR, month: int = 1, day: int = 1) -> datetime:
    """Timezone-aware start instant for FixedClock users (UTC midnight)."""
    return datetime(year, month, day, tzinfo=UTC)


def usd(amount: str) -> Decimal:
    """Decimal from a literal string, for scripted costs."""
    return Decimal(amount)
