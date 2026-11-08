"""Composer key handling: enter sends, ctrl+j and shift+enter break line, esc interrupts."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from caio_code.presentation.tui.widgets.composer import Composer

pytestmark = pytest.mark.tui


class ComposerHarness(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.submitted: list[str] = []
        self.interrupts = 0

    def compose(self) -> ComposeResult:
        yield Composer()

    def on_composer_submitted(self, message: Composer.Submitted) -> None:
        self.submitted.append(message.text)

    def on_composer_interrupt_requested(self, message: Composer.InterruptRequested) -> None:
        self.interrupts += 1


async def test_enter_submits_and_clears() -> None:
    app = ComposerHarness()
    async with app.run_test(headless=True, size=(60, 12)) as pilot:
        composer = app.query_one("#composer", Composer)
        composer.focus()
        composer.insert("fix the bug")
        await pilot.press("enter")
        await pilot.pause()
        assert app.submitted == ["fix the bug"]
        assert composer.text == ""


async def test_enter_with_empty_buffer_sends_nothing() -> None:
    app = ComposerHarness()
    async with app.run_test(headless=True, size=(60, 12)) as pilot:
        app.query_one("#composer", Composer).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.submitted == []


async def test_ctrl_j_inserts_newline_without_submitting() -> None:
    app = ComposerHarness()
    async with app.run_test(headless=True, size=(60, 12)) as pilot:
        composer = app.query_one("#composer", Composer)
        composer.focus()
        composer.insert("line one")
        await pilot.press("ctrl+j")
        composer.insert("line two")
        await pilot.pause()
        assert composer.text == "line one\nline two"
        assert app.submitted == []


async def test_shift_enter_inserts_newline() -> None:
    app = ComposerHarness()
    async with app.run_test(headless=True, size=(60, 12)) as pilot:
        composer = app.query_one("#composer", Composer)
        composer.focus()
        composer.insert("a")
        await pilot.press("shift+enter")
        composer.insert("b")
        await pilot.pause()
        assert composer.text == "a\nb"
        assert app.submitted == []


async def test_escape_requests_interrupt() -> None:
    app = ComposerHarness()
    async with app.run_test(headless=True, size=(60, 12)) as pilot:
        app.query_one("#composer", Composer).focus()
        await pilot.press("escape")
        await pilot.pause()
        assert app.interrupts == 1
