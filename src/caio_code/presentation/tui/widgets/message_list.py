"""The scrolling transcript: one bubble per message, one panel per tool call."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from caio_code.presentation.tui.theme import (
    DEFAULT_MAX_RENDERED_MESSAGES,
    MESSAGE_LIST_ID,
    ROLE_LABELS,
)
from caio_code.presentation.tui.widgets.tool_panel import ToolPanel


class MessageBubble(Vertical):
    """A single transcript message: coloured role header plus body text."""

    def __init__(self, message_id: str, role: str, text: str = "") -> None:
        super().__init__(id=f"message-{message_id}", classes=f"message message-{role}")
        self.message_id = message_id
        self.role = role
        self._text = text
        self._header = Static(
            ROLE_LABELS.get(role, role), classes="message-header", markup=False
        )
        self._body = Static(text, id=f"message-body-{message_id}", classes="message-body", markup=False)

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        """Replace the body; used by streaming deltas."""
        self._text = text
        self._body.update(text)

    def full_text(self) -> str:
        header = ROLE_LABELS.get(self.role, self.role)
        return f"{header}\n{self._text}"


Entry = MessageBubble | ToolPanel


class MessageList(VerticalScroll):
    """The transcript. Auto-scrolls to the bottom on every append.

    ``e`` expands or collapses the output of the most recent tool panel;
    individual panels also toggle with ``enter`` when focused.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("e", "expand_last_tool", "Expand tool output", show=False),
    ]

    def __init__(self, *, max_messages: int = DEFAULT_MAX_RENDERED_MESSAGES) -> None:
        super().__init__(id=MESSAGE_LIST_ID)
        if max_messages < 1:
            msg = f"max_messages must be positive, got {max_messages}"
            raise ValueError(msg)
        self._max_messages = max_messages
        self._entries: list[Entry] = []
        self._bubbles: dict[str, MessageBubble] = {}
        self._panels: dict[str, ToolPanel] = {}

    @property
    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._entries)

    def bubble(self, message_id: str) -> MessageBubble | None:
        return self._bubbles.get(message_id)

    def panel(self, call_id: str) -> ToolPanel | None:
        return self._panels.get(call_id)

    async def append_message(self, message_id: str, role: str, text: str = "") -> MessageBubble:
        """Add a new bubble; a repeated ``message_id`` is a caller error."""
        if message_id in self._bubbles:
            msg = f"message {message_id!r} already present in the transcript"
            raise ValueError(msg)
        bubble = MessageBubble(message_id, role, text)
        self._bubbles[message_id] = bubble
        self._entries.append(bubble)
        await self.mount(bubble)
        await self._trim()
        self.scroll_end(animate=False)
        return bubble

    async def update_message(self, message_id: str, text: str) -> bool:
        """Replace the text of an existing bubble (streaming delta)."""
        bubble = self._bubbles.get(message_id)
        if bubble is None:
            return False
        bubble.set_text(text)
        self.scroll_end(animate=False)
        return True

    async def add_tool_panel(self, call_id: str, tool: str, arguments: str) -> ToolPanel:
        panel = ToolPanel(call_id, tool, arguments)
        self._panels[call_id] = panel
        self._entries.append(panel)
        await self.mount(panel)
        await self._trim()
        self.scroll_end(animate=False)
        return panel

    async def _trim(self) -> None:
        """Drop the oldest widgets beyond ``max_messages`` (TuiConfig bound)."""
        while len(self._entries) > self._max_messages:
            oldest = self._entries.pop(0)
            if isinstance(oldest, MessageBubble):
                self._bubbles.pop(oldest.message_id, None)
            else:
                self._panels.pop(oldest.call_id, None)
            await oldest.remove()

    def action_expand_last_tool(self) -> None:
        for entry in reversed(self._entries):
            if isinstance(entry, ToolPanel):
                entry.toggle_result()
                return

    def full_text(self) -> str:
        """All transcript text, visible or scrolled away, collapsed or not."""
        return "\n".join(entry.full_text() for entry in self._entries)
