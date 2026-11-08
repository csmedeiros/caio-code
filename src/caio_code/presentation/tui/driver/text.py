"""Plain-text extraction from a running app, for assertions and txt dumps."""

from __future__ import annotations

from typing import Protocol

from textual.app import App
from textual.widget import Widget


class TextExportable(Protocol):
    """Widgets that can export their full text, visible or scrolled away."""

    def full_text(self) -> str: ...


def screen_text(app: App[object]) -> str:
    """The exact text currently painted on the screen, line by line."""
    strips = app.screen._compositor.render_strips()
    return "\n".join(strip.text for strip in strips).rstrip("\n")


def widget_text(widget: Widget) -> str:
    """Full text of one widget: ``full_text()`` when offered, else content.

    Containers without their own text aggregate the text of their children,
    so ``within='#sidebar'`` sees every line, scrolled away or not.
    """
    exportable = getattr(widget, "full_text", None)
    if callable(exportable):
        return str(exportable())
    content = getattr(widget, "text", None)
    if isinstance(content, str):
        return content
    if isinstance(getattr(widget, "content", None), str):
        return str(widget.content)
    children_text = [
        text for text in (widget_text(child) for child in widget.children) if text.strip()
    ]
    if children_text:
        return "\n".join(children_text)
    return str(widget.render())
