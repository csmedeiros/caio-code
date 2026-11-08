"""The multi-line input at the bottom of the screen.

``enter`` sends, ``shift+enter`` and ``ctrl+j`` insert a newline, ``escape``
asks the facade to interrupt the running turn. All four bindings are priority
bindings so they win over ``TextArea``'s own key handling.
"""

from __future__ import annotations

from typing import ClassVar

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea

from caio_code.presentation.tui.theme import COMPOSER_ID, COMPOSER_PLACEHOLDER


class Composer(TextArea):
    """Composer widget; talks to the app through messages, never to the agent."""

    class Submitted(Message):
        """The user pressed enter with a non-empty buffer."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class InterruptRequested(Message):
        """The user pressed escape while the composer had focus."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "submit", "Send", priority=True),
        Binding("shift+enter", "newline", "New line", priority=True),
        Binding("ctrl+j", "newline", "New line", priority=True),
        Binding("escape", "interrupt_turn", "Interrupt", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__(
            id=COMPOSER_ID,
            soft_wrap=True,
            show_line_numbers=False,
            placeholder=COMPOSER_PLACEHOLDER,
        )

    def action_submit(self) -> None:
        text = self.text.strip()
        if not text:
            return
        self.post_message(self.Submitted(text))
        self.clear()

    def action_newline(self) -> None:
        self.insert("\n")

    def action_interrupt_turn(self) -> None:
        self.post_message(self.InterruptRequested())
