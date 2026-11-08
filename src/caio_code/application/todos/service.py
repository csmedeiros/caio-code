"""Todo tracking use case: the agent's plan, as domain state.

The ``write_todos`` tool sends the whole list on every call, so the tracker's
only job is to turn raw arguments into a validated :class:`TodoBoard` and keep
the last one. Publishing ``TodoBoardUpdated`` is the runner's decision, not
this service's: two publishers would double every sidebar update. Pass
``publish=True`` only when nothing else owns the event.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from caio_code.domain.errors import ToolError
from caio_code.domain.events import EventBus, TodoBoardUpdated
from caio_code.domain.ports.time import Clock, IdentifierFactory
from caio_code.domain.todo.items import TodoBoard, TodoInvariantError, TodoItem, TodoStatus

TODO_ID_TEMPLATE = "todo-{index:04d}"
VALID_PRIORITIES = ("high", "medium", "low")
DEFAULT_PRIORITY = "medium"
MAX_CONTENT_CHARS = 400


@dataclass(frozen=True, slots=True)
class TodoDraft:
    """One item as the model wrote it, before validation."""

    content: str
    status: str = TodoStatus.PENDING.value
    priority: str = DEFAULT_PRIORITY
    id: str | None = None


class TodoTracker:
    """Holds the current board and rebuilds it from tool arguments."""

    def __init__(
        self,
        bus: EventBus,
        clock: Clock,
        identifiers: IdentifierFactory,
        *,
        publish: bool = False,
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._identifiers = identifiers
        self._publish = publish
        self._board = TodoBoard()
        self._revisions = 0

    @property
    def board(self) -> TodoBoard:
        return self._board

    @property
    def revisions(self) -> int:
        """How many times the board was replaced since construction."""
        return self._revisions

    @property
    def last_updated_at(self):
        """Instant of the last replacement, from the injected clock."""
        return self._clock.now()

    def replace_from_tool_arguments(self, raw_json: str, *, run_id: str) -> TodoBoard:
        """Parse a ``write_todos`` payload and replace the board."""
        drafts = parse_todo_arguments(raw_json)
        items = self._to_items(drafts)
        return self.replace(items, run_id=run_id)

    def replace(self, items: Sequence[TodoItem], *, run_id: str) -> TodoBoard:
        """Replace the board with a full list, renumbering display order."""
        board = self._board.replace(items)
        self._board = board
        self._revisions += 1
        if self._publish:
            self._bus.publish(TodoBoardUpdated(at=self._clock.now(), run_id=run_id, board=board))
        return board

    def mark(self, todo_id: str, status: TodoStatus, *, run_id: str) -> TodoBoard:
        """Change one item's status, keeping the single-in-progress invariant."""
        items: list[TodoItem] = []
        found = False
        for item in self._board.items:
            if item.id == todo_id:
                found = True
                items.append(item.with_status(status))
                continue
            if status is TodoStatus.IN_PROGRESS and item.status is TodoStatus.IN_PROGRESS:
                items.append(item.with_status(TodoStatus.PENDING))
                continue
            items.append(item)
        if not found:
            msg = f"todo {todo_id!r} is not on the board"
            raise TodoInvariantError(msg)
        return self.replace(items, run_id=run_id)

    def _to_items(self, drafts: Sequence[TodoDraft]) -> tuple[TodoItem, ...]:
        items: list[TodoItem] = []
        for index, draft in enumerate(drafts):
            content = " ".join(draft.content.split())
            if len(content) > MAX_CONTENT_CHARS:
                content = f"{content[: MAX_CONTENT_CHARS - 1]}…"
            items.append(
                TodoItem(
                    id=draft.id or TODO_ID_TEMPLATE.format(index=index),
                    content=content,
                    status=TodoStatus(draft.status),
                    priority=draft.priority,
                    order=index,
                )
            )
        return tuple(items)


def parse_todo_arguments(raw_json: str) -> list[TodoDraft]:
    """Accept both ``{"todos": [...]}`` and a bare list, with tolerant keys."""
    if not raw_json.strip():
        msg = "write_todos received empty arguments"
        raise ToolError(msg)
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        msg = f"write_todos arguments are not valid JSON: {exc.msg} at position {exc.pos}"
        raise ToolError(msg) from exc

    entries = payload.get("todos") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        msg = f"write_todos expects a list of todos, got {type(entries).__name__}"
        raise ToolError(msg)

    drafts: list[TodoDraft] = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            msg = f"todo {position} is not an object, got {type(entry).__name__}"
            raise ToolError(msg)
        content = entry.get("content") or entry.get("text") or entry.get("title") or ""
        if not isinstance(content, str) or not content.strip():
            msg = f"todo {position} has no content"
            raise ToolError(msg)
        status = str(entry.get("status") or TodoStatus.PENDING.value)
        if status not in {item.value for item in TodoStatus}:
            msg = f"todo {position} has unknown status {status!r}"
            raise ToolError(msg)
        priority = str(entry.get("priority") or DEFAULT_PRIORITY)
        if priority not in VALID_PRIORITIES:
            priority = DEFAULT_PRIORITY
        identifier = entry.get("id")
        drafts.append(
            TodoDraft(
                content=content,
                status=status,
                priority=priority,
                id=str(identifier) if identifier else None,
            )
        )
    return drafts
