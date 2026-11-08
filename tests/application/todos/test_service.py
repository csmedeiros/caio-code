"""Offline tests for the todo-tracking use case."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from caio_code.application.todos.service import MAX_CONTENT_CHARS, TodoTracker
from caio_code.domain.errors import ToolError
from caio_code.domain.events import InMemoryEventBus, TodoBoardUpdated
from caio_code.domain.todo.items import TodoInvariantError, TodoStatus
from caio_code.infrastructure.observability.bus import EventRecorder
from caio_code.infrastructure.observability.clocks import FixedClock, SequentialIdentifiers

START = datetime(2026, 1, 1, tzinfo=UTC)


def _tracker(*, publish: bool = False) -> tuple[TodoTracker, EventRecorder]:
    bus = InMemoryEventBus()
    recorder = EventRecorder()
    bus.subscribe(recorder)
    tracker = TodoTracker(bus, FixedClock(START), SequentialIdentifiers(), publish=publish)
    return tracker, recorder


def _payload(*todos: dict[str, object]) -> str:
    return json.dumps({"todos": list(todos)})


def test_replace_accepts_the_todos_object_and_a_bare_list() -> None:
    tracker, _ = _tracker()

    via_object = tracker.replace_from_tool_arguments(
        _payload({"content": "first"}, {"content": "second"}), run_id="run-1"
    )
    via_list = tracker.replace_from_tool_arguments(
        json.dumps([{"content": "only"}]), run_id="run-1"
    )

    assert [item.content for item in via_object.items] == ["first", "second"]
    assert [item.content for item in via_list.items] == ["only"]


def test_replace_keeps_supplied_ids_and_generates_sequential_ones() -> None:
    tracker, _ = _tracker()

    board = tracker.replace_from_tool_arguments(
        _payload({"content": "kept", "id": "custom-1"}, {"content": "generated"}),
        run_id="run-1",
    )

    assert [item.id for item in board.items] == ["custom-1", "todo-0001"]


def test_replace_renumbers_order_by_position() -> None:
    tracker, _ = _tracker()

    board = tracker.replace_from_tool_arguments(
        _payload(
            {"content": "a", "id": "x", "order": 99},
            {"content": "b", "id": "y"},
        ),
        run_id="run-1",
    )

    assert [item.order for item in board.items] == [0, 1]


def test_two_in_progress_items_break_the_single_in_progress_invariant() -> None:
    tracker, _ = _tracker()

    with pytest.raises(TodoInvariantError, match="at most one todo may be in progress"):
        tracker.replace_from_tool_arguments(
            _payload(
                {"content": "a", "status": "in_progress"},
                {"content": "b", "status": "in_progress"},
            ),
            run_id="run-1",
        )


def test_invalid_json_raises_tool_error_naming_the_problem() -> None:
    tracker, _ = _tracker()

    with pytest.raises(ToolError, match="not valid JSON"):
        tracker.replace_from_tool_arguments("{not json", run_id="run-1")


def test_non_list_payload_raises_tool_error() -> None:
    tracker, _ = _tracker()

    with pytest.raises(ToolError, match="expects a list of todos"):
        tracker.replace_from_tool_arguments(json.dumps({"todos": "nope"}), run_id="run-1")


def test_missing_content_raises_tool_error_naming_the_position() -> None:
    tracker, _ = _tracker()

    with pytest.raises(ToolError, match="todo 1 has no content"):
        tracker.replace_from_tool_arguments(
            _payload({"content": "ok"}, {"status": "pending"}), run_id="run-1"
        )


def test_unknown_status_raises_tool_error_naming_the_status() -> None:
    tracker, _ = _tracker()

    with pytest.raises(ToolError, match="unknown status 'exploded'"):
        tracker.replace_from_tool_arguments(
            _payload({"content": "a", "status": "exploded"}), run_id="run-1"
        )


def test_mark_moves_the_previous_in_progress_item_back_to_pending() -> None:
    tracker, _ = _tracker()
    tracker.replace_from_tool_arguments(
        _payload(
            {"content": "a", "id": "t0", "status": "in_progress"},
            {"content": "b", "id": "t1"},
        ),
        run_id="run-1",
    )

    board = tracker.mark("t1", TodoStatus.IN_PROGRESS, run_id="run-1")

    by_id = {item.id: item.status for item in board.items}
    assert by_id == {"t0": TodoStatus.PENDING, "t1": TodoStatus.IN_PROGRESS}


def test_default_publish_setting_publishes_nothing() -> None:
    tracker, recorder = _tracker()

    tracker.replace_from_tool_arguments(_payload({"content": "a"}), run_id="run-1")
    tracker.replace_from_tool_arguments(_payload({"content": "b"}), run_id="run-1")

    assert recorder.events == []


def test_publish_true_publishes_one_board_update_per_replace() -> None:
    tracker, recorder = _tracker(publish=True)

    tracker.replace_from_tool_arguments(_payload({"content": "a"}), run_id="run-1")
    tracker.replace_from_tool_arguments(_payload({"content": "b"}), run_id="run-1")

    updates = recorder.of_type(TodoBoardUpdated)
    assert len(updates) == 2
    assert all(event.run_id == "run-1" for event in updates)


def test_revisions_counts_replacements() -> None:
    tracker, _ = _tracker()

    assert tracker.revisions == 0
    tracker.replace_from_tool_arguments(_payload({"content": "a"}), run_id="run-1")
    tracker.replace_from_tool_arguments(_payload({"content": "b"}), run_id="run-1")

    assert tracker.revisions == 2


def test_content_longer_than_the_cap_is_truncated_with_an_ellipsis() -> None:
    tracker, _ = _tracker()

    board = tracker.replace_from_tool_arguments(
        _payload({"content": "x" * (MAX_CONTENT_CHARS + 50)}), run_id="run-1"
    )

    content = board.items[0].content
    assert len(content) == MAX_CONTENT_CHARS
    assert content.endswith("…")
