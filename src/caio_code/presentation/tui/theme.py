"""Named colours, sizes and CSS for the terminal interface.

Every visual constant lives here: widgets never contain colour or size
literals. The palette is light-on-dark and all foreground colours keep a
contrast ratio above 4.5:1 against ``COLOR_BACKGROUND``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Palette (light-on-dark)
# ---------------------------------------------------------------------------

COLOR_BACKGROUND = "#1a1b26"
COLOR_SURFACE = "#24283b"
COLOR_PANEL = "#1f2335"
COLOR_BORDER = "#3b4261"
COLOR_TEXT = "#c0caf5"
COLOR_TEXT_DIM = "#9aa5ce"
COLOR_ACCENT = "#7aa2f7"

COLOR_USER = "#7dcfff"
COLOR_ASSISTANT = "#9ece6a"
COLOR_TOOL = "#e0af68"
COLOR_SYSTEM = "#bb9af7"
COLOR_SUMMARY = "#f7768e"
COLOR_DANGER = "#f7768e"
COLOR_OK = "#9ece6a"

ROLE_COLORS: dict[str, str] = {
    "user": COLOR_USER,
    "assistant": COLOR_ASSISTANT,
    "tool": COLOR_TOOL,
    "system": COLOR_SYSTEM,
    "summary": COLOR_SUMMARY,
}

ROLE_LABELS: dict[str, str] = {
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "system": "system",
    "summary": "summary (anchored)",
}

# ---------------------------------------------------------------------------
# Sizes
# ---------------------------------------------------------------------------

DEFAULT_TERMINAL_SIZE: tuple[int, int] = (100, 30)
"""Terminal size used by headless tests and by the driver default."""

TRUNCATED_MARK = "[truncated]"
"""Marker appended to tool results that hit an output cap."""

COMPOSER_MIN_HEIGHT = 3
COMPOSER_MAX_HEIGHT = 10
COMPOSER_PLACEHOLDER = "Message the agent - enter sends, ctrl+j newline, esc interrupts"
MESSAGE_LIST_ID = "transcript"
SIDEBAR_ID = "sidebar"
COMPOSER_ID = "composer"
USAGE_FOOTER_ID = "usage-footer"
DEFAULT_MAX_RENDERED_MESSAGES = 400

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

APP_CSS = f"""
Screen {{
    background: {COLOR_BACKGROUND};
}}

#body {{
    height: 1fr;
}}

#{MESSAGE_LIST_ID} {{
    width: 1fr;
    height: 1fr;
    background: {COLOR_BACKGROUND};
    border-right: solid {COLOR_BORDER};
}}

#{SIDEBAR_ID} {{
    width: auto;
    height: 1fr;
    background: {COLOR_PANEL};
}}

#{COMPOSER_ID} {{
    height: auto;
    min-height: {COMPOSER_MIN_HEIGHT};
    max-height: {COMPOSER_MAX_HEIGHT};
    background: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: round {COLOR_BORDER};
    border-title-color: {COLOR_TEXT_DIM};
}}

#{USAGE_FOOTER_ID} {{
    height: 1;
    dock: bottom;
    background: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    padding: 0 1;
}}

#{USAGE_FOOTER_ID}.over-budget {{
    color: {COLOR_DANGER};
    text-style: bold;
}}

.message {{
    height: auto;
    margin: 0 1;
    padding: 0 1;
    border-left: thick {COLOR_BORDER};
}}

.message-header {{
    height: 1;
    text-style: bold;
}}

.message-body {{
    height: auto;
    color: {COLOR_TEXT};
}}

.message-user {{
    border-left: thick {COLOR_USER};
}}

.message-user .message-header {{
    color: {COLOR_USER};
}}

.message-assistant {{
    border-left: thick {COLOR_ASSISTANT};
}}

.message-assistant .message-header {{
    color: {COLOR_ASSISTANT};
}}

.message-tool {{
    border-left: thick {COLOR_TOOL};
}}

.message-system {{
    border-left: thick {COLOR_SYSTEM};
    color: {COLOR_SYSTEM};
}}

.message-system .message-header {{
    color: {COLOR_SYSTEM};
}}

.message-summary {{
    border: round {COLOR_SUMMARY};
    border-left: thick {COLOR_SUMMARY};
    background: {COLOR_PANEL};
}}

.message-summary .message-header {{
    color: {COLOR_SUMMARY};
    text-style: bold italic;
}}

.tool-panel {{
    height: auto;
    margin: 0 1;
    border: round {COLOR_BORDER};
    background: {COLOR_PANEL};
    padding: 0 1;
}}

.tool-header {{
    height: 1;
    color: {COLOR_TOOL};
    text-style: bold;
}}

.tool-args {{
    height: auto;
    color: {COLOR_TEXT_DIM};
}}

.tool-status {{
    height: 1;
    color: {COLOR_TEXT_DIM};
}}

.tool-status.error {{
    color: {COLOR_DANGER};
}}

#todo-header {{
    height: 1;
    dock: top;
    color: {COLOR_ACCENT};
    text-style: bold;
    padding: 0 1;
    background: {COLOR_SURFACE};
}}

.todo-item {{
    height: auto;
    color: {COLOR_TEXT_DIM};
    padding: 0 1;
}}

.todo-pending {{
    color: {COLOR_TEXT};
}}

.todo-in_progress {{
    color: {COLOR_ACCENT};
    background: {COLOR_SURFACE};
    text-style: bold;
}}

.todo-completed {{
    color: {COLOR_OK};
}}

.todo-cancelled {{
    color: {COLOR_TEXT_DIM};
    text-style: dim;
}}

#context-inspector-screen {{
    align: center middle;
}}

#context-inspector-dialog {{
    width: 70;
    height: auto;
    max-height: 80%;
    border: round {COLOR_ACCENT};
    background: {COLOR_PANEL};
    padding: 1 2;
}}

#context-inspector-title {{
    height: 1;
    color: {COLOR_ACCENT};
    text-style: bold;
}}

#context-inspector {{
    height: auto;
    max-height: 18;
    background: {COLOR_PANEL};
    color: {COLOR_TEXT};
}}

#context-inspector-empty {{
    height: auto;
    color: {COLOR_TEXT_DIM};
}}
"""
