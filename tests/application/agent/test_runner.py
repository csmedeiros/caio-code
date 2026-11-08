"""The runner use case: event order, accounting, interrupt, guard and todos."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool

from caio_code.application.agent.runner import AgentNotBuiltError, AgentRunner
from caio_code.application.agent.stub_model import StubChatModel, tool_turn
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.events import (
    ContextShaped,
    GuardrailFired,
    MessageAppended,
    RunFinished,
    RunStarted,
    TodoBoardUpdated,
    ToolCallIssued,
    UsageRecorded,
)
from caio_code.domain.todo.items import TodoStatus
from caio_code.infrastructure.observability.bus import EventRecorder
from tests.application.agent.conftest import event_names

BLOCK_TIMEOUT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.01
POLL_TIMEOUT_SECONDS = 10.0


class BlockingToolset:
    """A tool that parks on a threading.Event so interrupt() is observable."""

    def __init__(self, released: threading.Event) -> None:
        self._released = released

    def block(self) -> str:
        if not self._released.wait(BLOCK_TIMEOUT_SECONDS):
            msg = "blocking tool timed out before release"
            raise TimeoutError(msg)
        return "released"

    def as_langchain_tools(self) -> list[BaseTool]:
        return [
            StructuredTool.from_function(
                func=self.block,
                name="blocker",
                description="Block until the test releases the run.",
            )
        ]


async def wait_until(predicate: Callable[[], bool]) -> None:
    deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_SECONDS
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            msg = "condition never became true"
            raise TimeoutError(msg)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def test_full_stub_run_publishes_the_event_stream_in_order(
    make_runner: Callable[..., AgentRunner],
    recorder: EventRecorder,
) -> None:
    runner = make_runner()
    result = await runner.run("list the files and summarise them")

    names = event_names(recorder.events)
    assert names[0] == "RunStarted"
    assert names[-1] == "RunFinished"
    assert result.status == "completed"
    assert result.completed
    assert result.final_text
    assert result.accounting.usage.input_tokens > 0
    assert result.accounting.usage.output_tokens > 0
    assert result.context is not None
    assert result.transcript
    assert isinstance(recorder.of_type(ContextShaped)[0], ContextShaped)
    started = recorder.of_type(RunStarted)[0]
    assert started.task == "list the files and summarise them"
    finished = recorder.of_type(RunFinished)[0]
    assert finished.status == "completed"
    assert finished.error is None
    user_messages = [
        event for event in recorder.of_type(MessageAppended) if event.role == "user"
    ]
    assert user_messages and user_messages[0].preview.startswith("list the files")


async def test_run_before_build_raises_typed_error(
    make_runner: Callable[..., AgentRunner],
) -> None:
    runner = make_runner()
    runner._bundle = None
    with pytest.raises(AgentNotBuiltError, match="before build_agent"):
        await runner.run("anything")


async def test_interrupt_yields_interrupted_status(
    make_runner: Callable[..., AgentRunner],
    recorder: EventRecorder,
) -> None:
    released = threading.Event()
    turns = (tool_turn("blocker", {}), "never reached")
    runner = make_runner(turns, toolsets=(BlockingToolset(released),))

    run_task = asyncio.create_task(runner.run("interrupt me"))
    await wait_until(lambda: bool(recorder.of_type(ToolCallIssued)))
    runner.interrupt()
    released.set()
    result = await run_task

    assert result.status == "interrupted"
    finished = recorder.of_type(RunFinished)[0]
    assert finished.status == "interrupted"


async def test_guard_fires_on_third_identical_call_and_advisory_reaches_model(
    make_runner: Callable[..., AgentRunner],
    recorder: EventRecorder,
) -> None:
    chat_model = StubChatModel(
        turns=(
            tool_turn("list_directory", {"path": "."}),
            tool_turn("list_directory", {"path": "."}),
            tool_turn("list_directory", {"path": "."}),
            "stopped looping",
        )
    )
    runner = make_runner(chat_model=chat_model)
    result = await runner.run("loop please")

    assert result.status == "completed"
    issued = recorder.of_type(ToolCallIssued)
    assert len(issued) == 3
    fired = recorder.of_type(GuardrailFired)
    assert fired and fired[0].guardrail == "repeated_tool_call"
    tool_previews = [
        event.preview for event in recorder.of_type(MessageAppended) if event.role == "tool"
    ]
    assert any("guardrail" in preview for preview in tool_previews)
    # The advisory reached the model as the third tool result.
    last_call_messages = chat_model.calls[-1]
    advisory = [
        message
        for message in last_call_messages
        if isinstance(message, ToolMessage) and "guardrail" in str(message.content)
    ]
    assert advisory


async def test_write_todos_updates_board_and_publishes_event(
    make_runner: Callable[..., AgentRunner],
    recorder: EventRecorder,
) -> None:
    turns = (
        tool_turn(
            "write_todos",
            {
                "todos": [
                    {"content": "step one", "status": "in_progress"},
                    {"content": "step two", "status": "pending"},
                ]
            },
        ),
        "planned",
    )
    runner = make_runner(turns)
    result = await runner.run("plan the work")

    updates = recorder.of_type(TodoBoardUpdated)
    assert len(updates) == 1
    board = result.board
    assert len(board) == 2
    assert board.items[0].status is TodoStatus.IN_PROGRESS
    assert board.in_progress is not None
    assert board.in_progress.content == "step one"


async def test_usage_recorded_maps_cached_tokens(
    make_runner: Callable[..., AgentRunner],
    recorder: EventRecorder,
) -> None:
    chat_model = StubChatModel(turns=("answer",), cached_input_fraction=0.5)
    runner = make_runner(chat_model=chat_model)
    await runner.run("say something")

    usage_events = recorder.of_type(UsageRecorded)
    assert usage_events
    assert usage_events[0].usage.cached_input_tokens > 0
    assert usage_events[0].usage.input_tokens >= usage_events[0].usage.cached_input_tokens


async def test_streaming_deltas_share_one_message_id(
    make_runner: Callable[..., AgentRunner],
    recorder: EventRecorder,
) -> None:
    runner = make_runner()
    await runner.run("list")
    assistant_ids = [
        event.message_id
        for event in recorder.of_type(MessageAppended)
        if event.role == "assistant"
    ]
    assert assistant_ids
    assert len(set(assistant_ids)) == 1  # deltas and final share the id


def test_missing_collaborator_fallbacks_still_import() -> None:
    from caio_code.application.agent import bridges

    assert bridges.load_run_ledger_factory() is not None
    assert bridges.load_todo_tracker_factory() is not None
    assert bridges.load_guard_factory() is not None
    assert bridges.load_context_policy_middleware_factory() is not None


async def test_runner_rejects_empty_task(make_runner: Callable[..., AgentRunner]) -> None:
    runner = make_runner()
    with pytest.raises(ConfigurationError, match="task must not be empty"):
        await runner.run("   ")
