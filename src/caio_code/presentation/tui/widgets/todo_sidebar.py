"""The opencode-style todo sidebar: progress header plus one line per item."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from caio_code.domain.todo.items import TodoBoard, TodoItem, TodoStatus
from caio_code.presentation.tui.theme import SIDEBAR_ID

PROGRESS_SCALE = 100
PROGRESS_SEPARATOR = " · "
TODO_HEADER_ID = "todo-header"
TODO_ITEMS_ID = "todo-items"
EMPTY_HEADER = f"0/0{PROGRESS_SEPARATOR}0%"


def progress_text(board: TodoBoard) -> str:
    """``3/7 · 43%``: completed over countable items (cancelled excluded)."""
    countable = [item for item in board.items if item.status is not TodoStatus.CANCELLED]
    completed = len(board.completed)
    percent = round(board.progress_ratio * PROGRESS_SCALE)
    return f"{completed}/{len(countable)}{PROGRESS_SEPARATOR}{percent}%"


def item_classes(item: TodoItem) -> str:
    return f"todo-item todo-{item.status.value}"


class TodoSidebar(VerticalScroll):
    """Renders the current board; scrolls independently from the transcript."""

    def __init__(self) -> None:
        super().__init__(id=SIDEBAR_ID)
        self._board = TodoBoard()
        self._header = Static(EMPTY_HEADER, id=TODO_HEADER_ID, markup=False)
        self._items = Vertical(id=TODO_ITEMS_ID)

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._items

    @property
    def board(self) -> TodoBoard:
        return self._board

    @property
    def header_text(self) -> str:
        return str(self._header.content)

    def full_text(self) -> str:
        """Header plus every item line, whether scrolled into view or not."""
        lines = [self.header_text]
        lines.extend(f"{item.glyph} {item.content}" for item in self._board.sorted_items())
        return "\n".join(lines)

    async def update_board(self, board: TodoBoard) -> None:
        self._board = board
        self._header.update(progress_text(board))
        await self._items.remove_children()
        if board.items:
            await self._items.mount(
                *(
                    Static(
                        f"{item.glyph} {item.content}",
                        id=f"todo-{item.id}",
                        classes=item_classes(item),
                        markup=False,
                    )
                    for item in board.sorted_items()
                )
            )
