"""The Textual application: renders domain events, calls the facade, nothing else.

Threading model: the :class:`~caio_code.domain.events.EventBus` is synchronous
and may publish from any thread. The bus handler therefore only *posts* a
:class:`CaioCodeApp.DomainEventArrived` message; every widget mutation happens
on the Textual event loop, in message order. The app never imports application
or infrastructure modules; the agent is reached only through the injected
:class:`~caio_code.presentation.tui.ports.AgentFacade`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.message_pump import MessagePumpClosed
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Static

from caio_code.config import TuiConfig
from caio_code.domain.conversation.messages import Role
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
from caio_code.domain.ports.time import Clock
from caio_code.domain.usage.accounting import UsageLedger
from caio_code.presentation.tui.ports import (
    DEFAULT_MODEL,
    DEFAULT_POLICY,
    RUN_STATUS_ERROR,
    RUN_STATUS_INTERRUPTED,
    AgentFacade,
)
from caio_code.presentation.tui.theme import APP_CSS
from caio_code.presentation.tui.widgets.composer import Composer
from caio_code.presentation.tui.widgets.message_list import MessageList
from caio_code.presentation.tui.widgets.todo_sidebar import TodoSidebar
from caio_code.presentation.tui.widgets.usage_footer import (
    STATUS_COMPACTING,
    STATUS_ERROR,
    STATUS_FINISHED,
    STATUS_INTERRUPTED,
    STATUS_RUNNING,
    FooterState,
    UsageFooter,
)


class DomainEventArrived(Message):
    """One domain event handed from the bus thread to the Textual event loop.

    Module-level (not nested) so the derived handler name is stable:
    ``on_domain_event_arrived``.
    """

    def __init__(self, event: DomainEvent) -> None:
        super().__init__()
        self.event = event


CONTEXT_INSPECTOR_SCREEN_ID = "context-inspector-screen"
CONTEXT_INSPECTOR_ID = "context-inspector"
CONTEXT_INSPECTOR_TITLE_ID = "context-inspector-title"
CONTEXT_INSPECTOR_DIALOG_ID = "context-inspector-dialog"
CONTEXT_INSPECTOR_EMPTY_ID = "context-inspector-empty"
CONTEXT_INSPECTOR_TITLE = "context inspector (last decision)"
EMPTY_CONTEXT_TEXT = "no context decision recorded yet"
INSPECTOR_COLUMNS = ("field", "value")
GUARDRAIL_ID_PREFIX = "guardrail"
BODY_ID = "body"
HEADER_ID = "app-header"
KEYS_FOOTER_ID = "keys-footer"


def _cell(value: Any) -> str:
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{k}={_cell(v)}" for k, v in value.items()) + "}"
    if isinstance(value, Sequence) and not isinstance(value, str):
        return ", ".join(_cell(item) for item in value) if value else "(none)"
    return str(value)


def flatten_record(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Flatten a decision record into ``(field, value)`` table rows.

    Nested mappings become ``field.sub`` rows and lists of mappings become
    ``field[i].sub`` rows, so a pipeline decision fits the two-column table.
    """
    rows: list[tuple[str, str]] = []
    for key, value in record.items():
        if isinstance(value, Mapping):
            for sub_key, sub_value in value.items():
                rows.append((f"{key}.{sub_key}", _cell(sub_value)))
        elif (
            isinstance(value, Sequence)
            and not isinstance(value, str)
            and any(isinstance(item, Mapping) for item in value)
        ):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    for sub_key, sub_value in item.items():
                        rows.append((f"{key}[{index}].{sub_key}", _cell(sub_value)))
                else:
                    rows.append((f"{key}[{index}]", _cell(item)))
        else:
            rows.append((str(key), _cell(value)))
    return rows


class ContextInspectorScreen(ModalScreen[None]):
    """Modal (ctrl+u) showing the last context decision record as a table."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close_inspector", "Close", priority=True),
        Binding("ctrl+u", "close_inspector", "Close", priority=True),
    ]

    def __init__(self, record: Mapping[str, Any]) -> None:
        super().__init__(id=CONTEXT_INSPECTOR_SCREEN_ID)
        self._record = dict(record)

    def compose(self) -> ComposeResult:
        with Vertical(id=CONTEXT_INSPECTOR_DIALOG_ID):
            yield Static(CONTEXT_INSPECTOR_TITLE, id=CONTEXT_INSPECTOR_TITLE_ID, markup=False)
            if self._record:
                yield DataTable(id=CONTEXT_INSPECTOR_ID, cursor_type="row", zebra_stripes=True)
            else:
                yield Static(EMPTY_CONTEXT_TEXT, id=CONTEXT_INSPECTOR_EMPTY_ID, markup=False)

    def on_mount(self) -> None:
        if not self._record:
            return
        table = self.query_one(f"#{CONTEXT_INSPECTOR_ID}", DataTable)
        table.add_columns(*INSPECTOR_COLUMNS)
        table.add_rows(flatten_record(self._record))

    def action_close_inspector(self) -> None:
        self.dismiss(None)


class CaioCodeApp(App[None]):
    """The coding-agent terminal interface."""

    CSS = APP_CSS
    TITLE = "caio-code"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "interrupt", "Interrupt", priority=True),
        Binding("escape", "interrupt", "Interrupt", show=False),
        Binding("ctrl+t", "toggle_sidebar", "Todo", priority=True),
        Binding("ctrl+u", "inspect_context", "Context", priority=True),
        Binding("pageup", "scroll_up", "Scroll up", priority=True),
        Binding("pagedown", "scroll_down", "Scroll down", priority=True),
    ]

    def __init__(
        self,
        facade: AgentFacade,
        bus: EventBus,
        *,
        config: TuiConfig | None = None,
        clock: Clock | None = None,
    ) -> None:
        super().__init__()
        self._facade = facade
        self._bus = bus
        self._config = config or TuiConfig()
        self._clock = clock
        self._transcript = MessageList(max_messages=self._config.max_rendered_messages)
        self._sidebar = TodoSidebar()
        self._composer = Composer()
        self._footer = UsageFooter(FooterState(model=DEFAULT_MODEL, policy=DEFAULT_POLICY))
        self._sidebar_visible = self._config.show_sidebar
        self._accepting_events = False
        self._context_record: dict[str, Any] = {}
        self._ledger = UsageLedger(model=DEFAULT_MODEL)
        self._tool_started: dict[str, int] = {}
        self._guardrail_count = 0

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(id=HEADER_ID, show_clock=False)
        with Horizontal(id=BODY_ID):
            yield self._transcript
            yield self._sidebar
        yield self._composer
        yield self._footer
        yield Footer(id=KEYS_FOOTER_ID)

    def on_mount(self) -> None:
        self._sidebar.display = self._sidebar_visible
        self._sidebar.styles.width = self._config.sidebar_width
        self._accepting_events = True
        self._bus.subscribe(self._handle_domain_event)
        self._seed_from_facade()
        self._composer.focus()

    def on_unmount(self) -> None:
        self._accepting_events = False

    def _seed_from_facade(self) -> None:
        """Render whatever the facade already knows before the first event."""
        accounting = self._facade.accounting
        self._footer.update_state(
            model=accounting.model or DEFAULT_MODEL,
            input_tokens=accounting.usage.input_tokens,
            output_tokens=accounting.usage.output_tokens,
            cache_hit_ratio=accounting.cache.hit_ratio if accounting.cache.calls else None,
            cost_usd=accounting.cost.usd,
        )
        context = self._facade.context
        if context:
            self._context_record = dict(context)
            self._apply_context_record(context)
        board = self._facade.board
        if len(board):
            self.run_worker(self._sidebar.update_board(board))

    # ------------------------------------------------------------------
    # Bus bridge (never blocks the publisher)
    # ------------------------------------------------------------------

    def _handle_domain_event(self, event: DomainEvent) -> None:
        if not self._accepting_events:
            return
        try:
            self.post_message(DomainEventArrived(event))
        except MessagePumpClosed:
            self._accepting_events = False

    async def on_domain_event_arrived(self, message: DomainEventArrived) -> None:
        event = message.event
        match event:
            case RunStarted():
                self._ledger = UsageLedger(model=event.model)
                self._footer.update_state(
                    model=event.model, policy=event.policy, status=STATUS_RUNNING
                )
            case MessageAppended():
                await self._handle_message_appended(event)
            case ToolCallIssued():
                await self._transcript.add_tool_panel(event.call_id, event.tool, event.arguments)
                if self._clock is not None:
                    self._tool_started[event.call_id] = self._clock.monotonic_ms()
            case ToolCallCompleted():
                self._handle_tool_completed(event)
            case ContextShaped():
                self._context_record = dict(event.record)
                self._apply_context_record(event.record)
            case CompactionStarted():
                self._footer.update_state(status=STATUS_COMPACTING)
            case CompactionEnded():
                self._footer.update_state(status=STATUS_RUNNING)
            case TodoBoardUpdated():
                await self._sidebar.update_board(event.board)
            case GuardrailFired():
                await self._append_guardrail_notice(event)
            case UsageRecorded():
                self._handle_usage(event)
            case RunFinished():
                self._footer.update_state(status=self._finished_status(event.status))
            case _:
                pass

    def _finished_status(self, status: str) -> str:
        if status == RUN_STATUS_INTERRUPTED:
            return STATUS_INTERRUPTED
        if status == RUN_STATUS_ERROR:
            return STATUS_ERROR
        return STATUS_FINISHED

    async def _handle_message_appended(self, event: MessageAppended) -> None:
        panel = self._transcript.panel(event.message_id)
        if event.role == Role.TOOL and panel is not None:
            panel.set_result(event.preview)
            return
        if self._transcript.bubble(event.message_id) is not None:
            if self._config.stream_deltas:
                await self._transcript.update_message(event.message_id, event.preview)
            return
        await self._transcript.append_message(event.message_id, event.role, event.preview)

    def _handle_tool_completed(self, event: ToolCallCompleted) -> None:
        panel = self._transcript.panel(event.call_id)
        if panel is None:
            return
        started = self._tool_started.pop(event.call_id, None)
        elapsed_ms: int | None = None
        if started is not None and self._clock is not None:
            elapsed_ms = self._clock.monotonic_ms() - started
        panel.complete(
            chars=event.chars,
            truncated=event.truncated,
            error=event.error,
            elapsed_ms=elapsed_ms,
        )

    def _apply_context_record(self, record: Mapping[str, Any]) -> None:
        policy = record.get("policy") or record.get("pipeline")
        changes: dict[str, Any] = {
            "used_tokens": record.get("tokens_after"),
            "budget_tokens": record.get("budget_tokens"),
        }
        if isinstance(policy, str) and policy:
            changes["policy"] = policy
        self._footer.update_state(**changes)

    def _handle_usage(self, event: UsageRecorded) -> None:
        self._ledger.record(event.usage, cost=event.cost)
        accounting = self._ledger.accounting()
        self._footer.update_state(
            input_tokens=accounting.usage.input_tokens,
            output_tokens=accounting.usage.output_tokens,
            cache_hit_ratio=accounting.cache.hit_ratio,
            cost_usd=accounting.cost.usd,
            model=event.model or accounting.model,
        )

    async def _append_guardrail_notice(self, event: GuardrailFired) -> None:
        self._guardrail_count += 1
        message_id = f"{GUARDRAIL_ID_PREFIX}-{self._guardrail_count:04d}"
        text = f"guardrail {event.guardrail}: {event.detail}"
        await self._transcript.append_message(message_id, Role.SYSTEM, text)

    # ------------------------------------------------------------------
    # User input
    # ------------------------------------------------------------------

    def on_composer_submitted(self, message: Composer.Submitted) -> None:
        self.run_worker(self._facade.send(message.text), group="turn")

    def on_composer_interrupt_requested(self, message: Composer.InterruptRequested) -> None:
        self.run_worker(self._facade.interrupt(), group="interrupt")

    async def action_interrupt(self) -> None:
        await self._facade.interrupt()

    async def action_quit(self) -> None:
        self._accepting_events = False
        await self._facade.shutdown()
        self.exit()

    def action_toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        self._sidebar.display = self._sidebar_visible

    def action_inspect_context(self) -> None:
        if isinstance(self.screen, ContextInspectorScreen):
            return
        record = dict(self._context_record or self._facade.context)
        self.push_screen(ContextInspectorScreen(record))

    def action_scroll_up(self) -> None:
        self._transcript.scroll_page_up()

    def action_scroll_down(self) -> None:
        self._transcript.scroll_page_down()


__all__ = ["CaioCodeApp", "ContextInspectorScreen", "DomainEventArrived", "flatten_record"]
