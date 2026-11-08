"""MessageList and ToolPanel behaviour: bubbles, deltas, trim, expansion."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from caio_code.presentation.tui.theme import TRUNCATED_MARK
from caio_code.presentation.tui.widgets.message_list import MessageList
from caio_code.presentation.tui.widgets.tool_panel import (
    TOOL_ARGS_MAX_CHARS,
    ToolPanel,
    format_elapsed_ms,
    summarize_arguments,
)
from tests.presentation.tui.helpers import TEST_SIZE

pytestmark = pytest.mark.tui


class ListHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield MessageList(max_messages=3)


async def test_append_and_update_in_place() -> None:
    app = ListHarness()
    async with app.run_test(headless=True, size=TEST_SIZE) as pilot:
        listing = app.query_one("#transcript", MessageList)
        await listing.append_message("m1", "user", "hello")
        assert await listing.update_message("m1", "hello world") is True
        assert await listing.update_message("missing", "x") is False
        assert listing.bubble("m1") is not None
        assert listing.bubble("m1").text == "hello world"
        await pilot.pause()


async def test_duplicate_message_id_is_rejected() -> None:
    app = ListHarness()
    async with app.run_test(headless=True, size=TEST_SIZE):
        listing = app.query_one("#transcript", MessageList)
        await listing.append_message("m1", "user", "hello")
        with pytest.raises(ValueError, match="already present"):
            await listing.append_message("m1", "user", "again")


async def test_trim_drops_oldest_entries() -> None:
    app = ListHarness()
    async with app.run_test(headless=True, size=TEST_SIZE):
        listing = app.query_one("#transcript", MessageList)
        for index in range(5):
            await listing.append_message(f"m{index}", "assistant", f"text {index}")
        assert len(listing.entries) == 3
        assert listing.bubble("m0") is None
        assert listing.bubble("m4") is not None


async def test_tool_panel_result_collapsed_then_expanded_by_key() -> None:
    app = ListHarness()
    async with app.run_test(headless=True, size=TEST_SIZE) as pilot:
        listing = app.query_one("#transcript", MessageList)
        panel = await listing.add_tool_panel("c1", "read_file", '{"path": "a.py"}')
        panel.set_result("file contents here")
        panel.complete(chars=18, truncated=False, error=None, elapsed_ms=250)
        assert panel.collapsed is True
        listing.focus()
        await pilot.press("e")
        await pilot.pause()
        assert panel.collapsed is False
        await pilot.press("e")
        await pilot.pause()
        assert panel.collapsed is True


async def test_full_text_includes_collapsed_tool_output() -> None:
    app = ListHarness()
    async with app.run_test(headless=True, size=TEST_SIZE):
        listing = app.query_one("#transcript", MessageList)
        await listing.append_message("m1", "summary", "## Objective\n- keep going")
        panel = await listing.add_tool_panel("c1", "bash", "pytest -q")
        panel.set_result("2 passed")
        panel.complete(chars=8, truncated=True, error=None, elapsed_ms=900)
        full = listing.full_text()
        assert "## Objective" in full
        assert "2 passed" in full
        assert TRUNCATED_MARK in full


class TestToolPanelUnits:
    def test_summarize_arguments_truncates(self) -> None:
        long_args = "x" * (TOOL_ARGS_MAX_CHARS + 50)
        summary = summarize_arguments(long_args)
        assert len(summary) == TOOL_ARGS_MAX_CHARS
        assert summary.endswith("...")

    def test_summarize_arguments_flattens_whitespace(self) -> None:
        assert summarize_arguments("a\n  b\tc") == "a b c"

    def test_format_elapsed_ms(self) -> None:
        assert format_elapsed_ms(250) == "250 ms"
        assert format_elapsed_ms(1_500) == "1.5 s"

    def test_error_status_marks_panel(self) -> None:
        panel = ToolPanel("c1", "bash", "rm -rf /")
        panel.complete(chars=0, truncated=False, error="denied", elapsed_ms=None)
        assert panel.status_is_error is True
        assert panel.status_text.startswith("error: denied")
