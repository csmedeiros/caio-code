"""The facade implements the TUI's AgentFacade protocol over the runner."""

from __future__ import annotations

from collections.abc import Callable

from caio_code.application.agent.facade import AgentSessionFacade
from caio_code.application.agent.runner import AgentRunner
from caio_code.domain.events import MessageAppended, RunFinished, RunStarted
from caio_code.infrastructure.observability.bus import EventRecorder
from caio_code.presentation.tui.ports import AgentFacade
from tests.application.agent.conftest import event_names


async def test_facade_satisfies_the_protocol(
    make_runner: Callable[..., AgentRunner],
) -> None:
    facade = AgentSessionFacade(make_runner())
    assert isinstance(facade, AgentFacade)


async def test_send_runs_and_exposes_state(
    make_runner: Callable[..., AgentRunner],
    recorder: EventRecorder,
) -> None:
    facade = AgentSessionFacade(make_runner())
    assert facade.run_id == ""
    assert facade.context == {}

    await facade.send("list the files please")

    assert facade.run_id
    accounting = facade.accounting
    assert accounting.usage.input_tokens > 0
    context = facade.context
    assert context["policy"] == "sliding_window"
    assert context["budget_tokens"] > 0
    assert facade.board is not None
    assert facade.last_result is not None
    assert facade.last_result.status == "completed"

    names = event_names(recorder.events)
    assert names[0] == "RunStarted"
    assert names[-1] == "RunFinished"
    user_events = [
        event for event in recorder.of_type(MessageAppended) if event.role == "user"
    ]
    assert user_events[0].preview == "list the files please"


async def test_interrupt_stops_the_turn(
    make_runner: Callable[..., AgentRunner],
) -> None:
    facade = AgentSessionFacade(make_runner())
    await facade.interrupt()  # no active run: must not raise
    await facade.shutdown()


async def test_run_started_is_published_once_per_send(
    make_runner: Callable[..., AgentRunner],
    recorder: EventRecorder,
) -> None:
    facade = AgentSessionFacade(make_runner())
    await facade.send("first")
    await facade.send("second")
    assert len(recorder.of_type(RunStarted)) == 2
    assert len(recorder.of_type(RunFinished)) == 2
