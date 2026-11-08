"""Bordered panel for one tool call: name, arguments, result, status.

The result preview is collapsed by default and expands with ``enter`` on the
focused collapsible, with a click on its title, or with the ``e`` binding of
:class:`~caio_code.presentation.tui.widgets.message_list.MessageList`.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Collapsible, Static

from caio_code.presentation.tui.theme import TRUNCATED_MARK

TOOL_ARGS_MAX_CHARS = 200
TOOL_RESULT_MAX_CHARS = 600
PENDING_LABEL = "running"
OUTPUT_TITLE = "output"
ELLIPSIS = "..."
MS_PER_SECOND = 1_000


def summarize_arguments(arguments: str, *, limit: int = TOOL_ARGS_MAX_CHARS) -> str:
    """One-line, length-bounded view of the call arguments."""
    flat = " ".join(arguments.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - len(ELLIPSIS)] + ELLIPSIS


def format_elapsed_ms(elapsed_ms: int) -> str:
    """Human-readable elapsed time; sub-second values stay in milliseconds."""
    if elapsed_ms < MS_PER_SECOND:
        return f"{elapsed_ms} ms"
    return f"{elapsed_ms / MS_PER_SECOND:.1f} s"


class ToolPanel(Vertical):
    """Visual trace of one tool call, keyed by its ``call_id``."""

    def __init__(self, call_id: str, tool: str, arguments: str) -> None:
        super().__init__(id=f"tool-panel-{call_id}", classes="tool-panel")
        self.call_id = call_id
        self.tool_name = tool
        self.arguments_text = summarize_arguments(arguments)
        self.result_text = ""
        self.status_text = PENDING_LABEL
        self.status_is_error = False
        self._result_static = Static("", id=f"tool-output-{call_id}", markup=False)
        self._status_static = Static(
            self.status_text, id=f"tool-status-{call_id}", classes="tool-status", markup=False
        )
        self._collapsible = Collapsible(
            self._result_static,
            title=OUTPUT_TITLE,
            collapsed=True,
            id=f"tool-result-{call_id}",
        )

    def compose(self) -> ComposeResult:
        yield Static(
            f"tool {self.tool_name}",
            id=f"tool-header-{self.call_id}",
            classes="tool-header",
            markup=False,
        )
        yield Static(
            self.arguments_text, id=f"tool-args-{self.call_id}", classes="tool-args", markup=False
        )
        yield self._collapsible
        yield self._status_static

    def set_result(self, preview: str) -> None:
        """Store the result text; only the bounded preview is displayed."""
        self.result_text = preview
        shown = preview
        if len(shown) > TOOL_RESULT_MAX_CHARS:
            shown = shown[: TOOL_RESULT_MAX_CHARS - len(ELLIPSIS)] + ELLIPSIS
        self._result_static.update(shown)

    def complete(
        self,
        *,
        chars: int,
        truncated: bool,
        error: str | None = None,
        elapsed_ms: int | None = None,
    ) -> None:
        """Mark the call finished and refresh the status line."""
        parts = []
        if error is not None:
            parts.append(f"error: {error}")
        else:
            parts.append("done")
        parts.append(f"{chars} chars")
        if elapsed_ms is not None:
            parts.append(format_elapsed_ms(elapsed_ms))
        if truncated:
            parts.append(TRUNCATED_MARK)
        self.status_text = " · ".join(parts)
        self.status_is_error = error is not None
        self._status_static.update(self.status_text)
        self._status_static.set_class(error is not None, "error")

    @property
    def collapsed(self) -> bool:
        return bool(self._collapsible.collapsed)

    def toggle_result(self) -> None:
        """Expand or collapse the result preview."""
        self._collapsible.collapsed = not self._collapsible.collapsed

    def full_text(self) -> str:
        """Every text line of the panel, including collapsed content."""
        lines = [
            f"tool {self.tool_name}",
            self.arguments_text,
            OUTPUT_TITLE,
            self.result_text,
            self.status_text,
        ]
        return "\n".join(lines)
