"""Todo tracking: the state the sidebar renders.

The board is domain, not widget: the TUI, the CLI and the eval reports read the
same object, so what the user sees is what was measured.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from caio_code.domain.errors import CaioCodeError


class TodoStatus(StrEnum):
    """Lifecycle of one item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

    @property
    def is_open(self) -> bool:
        return self in {TodoStatus.PENDING, TodoStatus.IN_PROGRESS}


class TodoInvariantError(CaioCodeError):
    """A todo list broke one of its rules."""


ACTIVE_STATUSES = (TodoStatus.PENDING, TodoStatus.IN_PROGRESS, TodoStatus.COMPLETED)
GLYPHS = {
    TodoStatus.PENDING: "[ ]",
    TodoStatus.IN_PROGRESS: "[~]",
    TodoStatus.COMPLETED: "[x]",
    TodoStatus.CANCELLED: "[-]",
}


@dataclass(frozen=True, slots=True)
class TodoItem:
    """One tracked step."""

    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING
    priority: str = "medium"
    order: int = 0

    def __post_init__(self) -> None:
        if not self.content.strip():
            msg = f"todo {self.id!r} has empty content"
            raise TodoInvariantError(msg)
        if self.order < 0:
            msg = f"todo {self.id!r} has negative order {self.order}"
            raise TodoInvariantError(msg)

    @property
    def glyph(self) -> str:
        return GLYPHS[self.status]

    def with_status(self, status: TodoStatus) -> TodoItem:
        return TodoItem(
            id=self.id,
            content=self.content,
            status=status,
            priority=self.priority,
            order=self.order,
        )


@dataclass(frozen=True, slots=True)
class TodoBoard:
    """An ordered list of items with at most one in progress.

    ``replace`` is the only mutation: the agent's ``write_todos`` tool sends the
    whole list every time, exactly as in the harnesses this prototype mirrors.
    """

    items: tuple[TodoItem, ...] = ()

    @classmethod
    def of(cls, items: Iterable[TodoItem]) -> TodoBoard:
        materialized = tuple(items)
        board = cls(materialized)
        board.validate()
        return board

    def validate(self) -> None:
        in_progress = [item for item in self.items if item.status is TodoStatus.IN_PROGRESS]
        if len(in_progress) > 1:
            names = ", ".join(item.id for item in in_progress)
            msg = f"at most one todo may be in progress, got {len(in_progress)}: {names}"
            raise TodoInvariantError(msg)
        ids = [item.id for item in self.items]
        if len(set(ids)) != len(ids):
            msg = f"duplicate todo ids: {sorted(ids)}"
            raise TodoInvariantError(msg)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def completed(self) -> tuple[TodoItem, ...]:
        return tuple(item for item in self.items if item.status is TodoStatus.COMPLETED)

    @property
    def open_items(self) -> tuple[TodoItem, ...]:
        return tuple(item for item in self.items if item.status.is_open)

    @property
    def in_progress(self) -> TodoItem | None:
        for item in self.items:
            if item.status is TodoStatus.IN_PROGRESS:
                return item
        return None

    @property
    def progress_ratio(self) -> float:
        """Completed over countable items, in [0, 1]. Cancelled items do not count."""
        countable = [item for item in self.items if item.status is not TodoStatus.CANCELLED]
        if not countable:
            return 0.0
        return len(self.completed) / len(countable)

    def sorted_items(self) -> tuple[TodoItem, ...]:
        """Stable display order: by order, then by id. Never by hash."""
        return tuple(sorted(self.items, key=lambda item: (item.order, item.id)))

    def replace(self, items: Sequence[TodoItem]) -> TodoBoard:
        """A new board from a full list, renumbering display order deterministically."""
        renumbered = tuple(
            TodoItem(
                id=item.id,
                content=item.content,
                status=item.status,
                priority=item.priority,
                order=position,
            )
            for position, item in enumerate(items)
        )
        return TodoBoard.of(renumbered)

    def as_records(self) -> list[dict[str, str | int]]:
        """Serializable view for reports and for the TUI driver assertions."""
        return [
            {
                "id": item.id,
                "content": item.content,
                "status": item.status.value,
                "priority": item.priority,
                "order": item.order,
            }
            for item in self.sorted_items()
        ]
