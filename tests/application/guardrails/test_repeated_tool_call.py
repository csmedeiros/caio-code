"""Offline tests for the repeated-tool-call guardrail."""

from __future__ import annotations

from datetime import UTC, datetime

from caio_code.application.guardrails.repeated_tool_call import (
    EPOCH,
    GUARDRAIL_NAME,
    RepeatedToolCallGuard,
    normalize_arguments,
)
from caio_code.config import GuardrailConfig
from caio_code.domain.events import GuardrailFired, InMemoryEventBus
from caio_code.infrastructure.observability.bus import EventRecorder
from caio_code.infrastructure.observability.clocks import FixedClock

START = datetime(2026, 1, 1, tzinfo=UTC)
CALL_ARGS = '{"path": "src/main.py"}'


def _guard(
    *,
    max_repeats: int = 3,
    window_messages: int = 12,
    with_clock: bool = True,
) -> tuple[RepeatedToolCallGuard, EventRecorder]:
    bus = InMemoryEventBus()
    recorder = EventRecorder()
    bus.subscribe(recorder)
    clock = FixedClock(START) if with_clock else None
    guard = RepeatedToolCallGuard(
        GuardrailConfig(max_repeats=max_repeats, window_messages=window_messages),
        bus,
        clock,
    )
    return guard, recorder


def test_first_two_identical_calls_do_not_fire_and_the_third_fires() -> None:
    guard, recorder = _guard()

    first = guard.inspect("read_file", CALL_ARGS, run_id="run-1")
    second = guard.inspect("read_file", CALL_ARGS, run_id="run-1")
    third = guard.inspect("read_file", CALL_ARGS, run_id="run-1")

    assert (first.fired, first.repeats) == (False, 1)
    assert (second.fired, second.repeats) == (False, 2)
    assert third.fired
    assert third.repeats == 3
    assert "read_file" in third.advisory
    assert third.advisory != ""
    assert len(recorder.of_type(GuardrailFired)) == 1


def test_calls_with_different_arguments_never_fire() -> None:
    guard, recorder = _guard()

    for index in range(6):
        verdict = guard.inspect(
            "read_file", f'{{"path": "src/m{index}.py"}}', run_id="run-1"
        )
        assert not verdict.fired

    assert recorder.events == []


def test_normalize_arguments_hides_neither_key_order_nor_whitespace() -> None:
    assert normalize_arguments('{"b": 1, "a": 2}') == normalize_arguments('{"a":2,"b":1}')
    assert normalize_arguments("  not   json ") == "not json"
    assert normalize_arguments("   ") == ""


def test_key_order_and_whitespace_do_not_hide_a_repeat_from_the_guard() -> None:
    guard, _ = _guard()

    guard.inspect("edit", '{"a": 1, "b": 2}', run_id="run-1")
    guard.inspect("edit", '{"b":2,"a":1}', run_id="run-1")
    verdict = guard.inspect("edit", '{ "a" : 1 , "b" : 2 }', run_id="run-1")

    assert verdict.fired
    assert verdict.repeats == 3


def test_the_same_call_can_fire_again_after_the_window_slides_past() -> None:
    guard, recorder = _guard(window_messages=3)

    verdicts = [
        guard.inspect("shell", '{"cmd": "pytest"}', run_id="run-1").fired
        for _ in range(3)
    ]
    assert verdicts == [False, False, True]
    for index in range(3):
        guard.inspect("shell", f'{{"cmd": "ls {index}"}}', run_id="run-1")

    assert not guard.inspect("shell", '{"cmd": "pytest"}', run_id="run-1").fired
    assert not guard.inspect("shell", '{"cmd": "pytest"}', run_id="run-1").fired
    assert guard.inspect("shell", '{"cmd": "pytest"}', run_id="run-1").fired
    assert len(recorder.of_type(GuardrailFired)) == 2


def test_guardrail_fired_event_names_the_guardrail_and_the_tool() -> None:
    guard, recorder = _guard()

    for _ in range(3):
        guard.inspect("search", '{"q": "TODO"}', run_id="run-7")

    events = recorder.of_type(GuardrailFired)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, GuardrailFired)
    assert event.guardrail == GUARDRAIL_NAME
    assert "search" in event.detail
    assert event.run_id == "run-7"


def test_reset_clears_the_window_and_the_firing_count() -> None:
    guard, _ = _guard()
    for _ in range(3):
        guard.inspect("read_file", CALL_ARGS, run_id="run-1")

    guard.reset()

    assert guard.recent_calls == ()
    assert guard.firings == 0
    assert not guard.inspect("read_file", CALL_ARGS, run_id="run-1").fired


def test_without_a_clock_the_event_is_still_published_stamped_with_the_epoch() -> None:
    guard, recorder = _guard(with_clock=False)

    for _ in range(3):
        guard.inspect("read_file", CALL_ARGS, run_id="run-1")

    events = recorder.of_type(GuardrailFired)
    assert len(events) == 1
    assert events[0].at == EPOCH
