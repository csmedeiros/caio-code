"""TodoSidebar rendering: progress header, glyphs, status classes."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from caio_code.domain.todo.items import TodoBoard, TodoItem, TodoStatus
from caio_code.presentation.tui.widgets.todo_sidebar import TodoSidebar, progress_text
from tests.presentation.tui.helpers import TEST_SIZE

pytestmark = pytest.mark.tui


def make_board() -> TodoBoard:
    return TodoBoard.of(
        (
            TodoItem(id="t1", content="read the code", status=TodoStatus.COMPLETED, order=0),
            TodoItem(id="t2", content="patch the bug", status=TodoStatus.IN_PROGRESS, order=1),
            TodoItem(id="t3", content="write tests", status=TodoStatus.PENDING, order=2),
            TodoItem(id="t4", content="old plan", status=TodoStatus.CANCELLED, order=3),
        )
    )


class SidebarHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield TodoSidebar()


def test_progress_text_counts_only_countable_items() -> None:
    assert progress_text(make_board()) == "1/3 · 33%"
    assert progress_text(TodoBoard()) == "0/0 · 0%"


async def test_update_board_renders_items_with_glyphs_and_classes() -> None:
    app = SidebarHarness()
    async with app.run_test(headless=True, size=TEST_SIZE) as pilot:
        sidebar = app.query_one("#sidebar", TodoSidebar)
        await sidebar.update_board(make_board())
        await pilot.pause()
        assert sidebar.header_text == "1/3 · 33%"
        items = sidebar.query(".todo-item")
        assert len(items) == 4
        assert len(sidebar.query(".todo-in_progress")) == 1
        assert len(sidebar.query(".todo-completed")) == 1
        assert len(sidebar.query(".todo-cancelled")) == 1
        full = sidebar.full_text()
        assert "[x] read the code" in full
        assert "[~] patch the bug" in full
        assert "[ ] write tests" in full
        assert "[-] old plan" in full


async def test_board_replacement_is_atomic() -> None:
    app = SidebarHarness()
    async with app.run_test(headless=True, size=TEST_SIZE) as pilot:
        sidebar = app.query_one("#sidebar", TodoSidebar)
        await sidebar.update_board(make_board())
        await sidebar.update_board(
            TodoBoard.of((TodoItem(id="n1", content="fresh list", order=0),))
        )
        await pilot.pause()
        assert len(sidebar.query(".todo-item")) == 1
        assert sidebar.header_text == "0/1 · 0%"
