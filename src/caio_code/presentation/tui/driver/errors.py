"""Typed errors of the headless driver."""

from __future__ import annotations

from typing import TYPE_CHECKING

from caio_code.domain.errors import CaioCodeError

ACTUAL_PREVIEW_CHARS = 400
PREVIEW_ELLIPSIS = "..."

if TYPE_CHECKING:
    from caio_code.presentation.tui.driver.report import DriverReport


class DriverError(CaioCodeError):
    """Base of every driver failure."""


class ScenarioError(DriverError):
    """A scenario could not be resolved or set up."""


class ScriptError(DriverError):
    """A --script line is malformed or uses an unknown verb."""


class DriverAssertionError(DriverError):
    """A step assertion failed; the message names step, expected and actual."""

    def __init__(
        self,
        step_index: int,
        expected: str,
        actual: str,
        *,
        report: DriverReport | None = None,
    ) -> None:
        self.step_index = step_index
        self.expected = expected
        self.actual = actual
        self.report = report
        preview = actual
        if len(preview) > ACTUAL_PREVIEW_CHARS:
            preview = preview[:ACTUAL_PREVIEW_CHARS] + PREVIEW_ELLIPSIS
        super().__init__(f"step {step_index}: expected {expected!r}, actual {preview!r}")


class WidgetLookupError(DriverError):
    """A selector matched no widget, or matched more than one."""
