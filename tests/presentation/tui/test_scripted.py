"""Unit tests of the ScriptedFacade: determinism, interruption, contract."""

from __future__ import annotations

import asyncio
import itertools

import pytest

from caio_code.domain.events import MessageAppended, RunFinished, RunStarted, TodoBoardUpdated
from caio_code.domain.usage.accounting import TokenUsage
from caio_code.infrastructure.observability.bus import to_record
from caio_code.presentation.tui.ports import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_INTERRUPTED,
    AgentFacade,
)
from caio_code.presentation.tui.scripted import (
    AssistantStep,
    AwaitInterruptStep,
    ContextStep,
    FinishStep,
    ScriptedFacade,
    ScriptedFacadeError,
    TodoStep,
    UsageStep,
    split_deltas,
)
from tests.presentation.tui.helpers import TuiRig

pytestmark = pytest.mark.tui


class TestSplitDeltas:
    def test_prefixes_grow_and_end_with_full_text(self) -> None:
        prefixes = split_deltas("abcdefgh", 4)
        assert prefixes[-1] == "abcdefgh"
        assert all(prefixes[i] == "abcdefgh"[: len(prefixes[i])] for i in range(len(prefixes)))
        assert all(len(a) < len(b) for a, b in itertools.pairwise(prefixes))

    def test_single_delta_is_the_full_text(self) -> None:
        assert split_deltas("hello", 1) == ("hello",)

    def test_empty_text(self) -> None:
        assert split_deltas("", 3) == ("",)

    def test_non_positive_parts_rejected(self) -> None:
        with pytest.raises(ScriptedFacadeError):
            split_deltas("x", 0)


class TestReplay:
    async def test_send_publishes_deterministic_event_stream(self, rig_factory) -> None:
        script = (
            AssistantStep("hi there", deltas=2),
            TodoStep((("task one", "in_progress"), ("task two", "pending"))),
            UsageStep(usage=TokenUsage(input_tokens=100, output_tokens=10)),
            FinishStep(),
        )
        first: TuiRig = rig_factory(script)
        second: TuiRig = rig_factory(script)
        await first.facade.send("same input")
        await second.facade.send("same input")
        assert [to_record(event) for event in first.facade.events] == [
            to_record(event) for event in second.facade.events
        ]

    async def test_event_order_and_roles(self, rig_factory) -> None:
        rig = rig_factory((AssistantStep("reply", deltas=2), FinishStep()))
        await rig.facade.send("question")
        events = rig.facade.events
        assert isinstance(events[0], RunStarted)
        assert isinstance(events[1], MessageAppended)
        assert events[1].role == "user"
        assert events[1].preview == "question"
        assert [event.role for event in events[2:-1] if isinstance(event, MessageAppended)] == [
            "assistant",
            "assistant",
        ]
        assert isinstance(events[-1], RunFinished)
        assert events[-1].status == RUN_STATUS_COMPLETED

    async def test_todo_step_updates_board_and_publishes(self, rig_factory) -> None:
        rig = rig_factory((TodoStep((("a", "completed"), ("b", "pending"))), FinishStep()))
        await rig.facade.send("plan")
        assert len(rig.facade.board) == 2
        assert any(isinstance(event, TodoBoardUpdated) for event in rig.facade.events)

    async def test_interrupt_finishes_run_once(self, rig_factory) -> None:
        rig = rig_factory((AwaitInterruptStep(), FinishStep()))
        task = asyncio.ensure_future(rig.facade.send("long task"))
        await asyncio.sleep(0)
        await rig.facade.interrupt()
        await task
        finished = [event for event in rig.facade.events if isinstance(event, RunFinished)]
        assert len(finished) == 1
        assert finished[0].status == RUN_STATUS_INTERRUPTED

    async def test_send_while_running_raises(self, rig_factory) -> None:
        rig = rig_factory((AwaitInterruptStep(),))
        first = asyncio.ensure_future(rig.facade.send("one"))
        await asyncio.sleep(0)
        with pytest.raises(ScriptedFacadeError, match="still replaying"):
            await rig.facade.send("two")
        await rig.facade.interrupt()
        await first

    async def test_context_property_is_the_last_decision_record(self, rig_factory) -> None:
        rig = rig_factory(
            (ContextStep(policy="p", tokens_before=10, tokens_after=5, budget_tokens=8),)
        )
        assert rig.facade.context == {}
        await rig.facade.send("go")
        assert rig.facade.context["policy"] == "p"
        assert rig.facade.context["overflow_tokens"] == 0
        assert rig.facade.context["tokens_saved"] == 5

    async def test_shutdown_is_counted_and_idempotent(self, rig_factory) -> None:
        rig = rig_factory()
        await rig.facade.shutdown()
        await rig.facade.shutdown()
        assert rig.facade.shutdown_calls == 2

    async def test_facade_satisfies_protocol(self, rig_factory) -> None:
        rig: TuiRig = rig_factory()
        assert isinstance(rig.facade, AgentFacade)
        assert isinstance(rig.facade, ScriptedFacade)
