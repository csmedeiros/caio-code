"""Offline tests for the event recorder and the JSONL handler."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from caio_code.domain.events import (
    CompactionEnded,
    CompactionStarted,
    ContextShaped,
    DomainEvent,
    GuardrailFired,
    MessageAppended,
    RunFinished,
    RunStarted,
    TodoBoardUpdated,
    ToolCallCompleted,
    ToolCallIssued,
    UsageRecorded,
)
from caio_code.domain.policy.base import PolicyDecision
from caio_code.domain.todo.items import TodoBoard, TodoItem, TodoStatus
from caio_code.domain.usage.accounting import Cost, TokenUsage
from caio_code.infrastructure.observability.bus import (
    EventRecorder,
    JsonlEventHandler,
    to_record,
)
from caio_code.infrastructure.observability.clocks import FixedClock
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
USAGE = TokenUsage(input_tokens=10, output_tokens=4, cached_input_tokens=2)
COST = Cost(Decimal("0.001234"))


def _all_events() -> list[DomainEvent]:
    board = TodoBoard.of(
        [TodoItem(id="t1", content="write tests", status=TodoStatus.IN_PROGRESS)]
    )
    decision = PolicyDecision(
        policy="sliding_window",
        kept_indices=(0, 1),
        counter=CharProxyTokenCounter(),
        tokens_before=100,
        tokens_after=40,
        budget_tokens=50,
    )
    return [
        RunStarted(at=AT, run_id="r1", task="fix bug", model="m", policy="sliding_window"),
        MessageAppended(at=AT, run_id="r1", message_id="m1", role="user", chars=9, preview="fix bug"),
        ToolCallIssued(at=AT, run_id="r1", tool="read", arguments="{}", call_id="c1"),
        ToolCallCompleted(at=AT, run_id="r1", tool="read", call_id="c1", chars=12, truncated=False),
        ContextShaped(at=AT, run_id="r1", decision=decision),
        CompactionStarted(at=AT, run_id="r1", head_chars=500, previous_summary=False),
        CompactionEnded(
            at=AT,
            run_id="r1",
            summary_chars=300,
            sections=8,
            well_formed=True,
            usage=USAGE,
            cost=COST,
            latency_ms=15,
        ),
        TodoBoardUpdated(at=AT, run_id="r1", board=board),
        GuardrailFired(at=AT, run_id="r1", guardrail="repeat", detail="ls x3"),
        UsageRecorded(at=AT, run_id="r1", usage=USAGE, cost=COST, model="m", latency_ms=8),
        RunFinished(at=AT, run_id="r1", status="ok", usage=USAGE, cost=COST, compactions=1),
    ]


def test_to_record_covers_every_event_class() -> None:
    events = _all_events()
    records = [to_record(event) for event in events]
    assert len(records) == len(events)
    assert {record["event"] for record in records} == {
        type(event).__name__ for event in events
    }
    for record in records:
        assert record["at"] == AT.isoformat()
        assert record["run_id"] == "r1"
        # Every record must survive a JSON round trip.
        assert json.loads(json.dumps(record, ensure_ascii=False))


def test_to_record_carries_event_specific_fields() -> None:
    events = {type(event).__name__: to_record(event) for event in _all_events()}
    assert events["RunStarted"]["task"] == "fix bug"
    assert events["MessageAppended"]["preview"] == "fix bug"
    assert events["ToolCallIssued"]["call_id"] == "c1"
    assert events["ToolCallCompleted"]["truncated"] is False
    assert events["ContextShaped"]["decision"]["policy"] == "sliding_window"
    assert events["CompactionStarted"]["head_chars"] == 500
    assert events["CompactionEnded"]["usage"]["cached_input_tokens"] == 2
    assert events["CompactionEnded"]["cost_usd"] == "0.001234"
    assert events["TodoBoardUpdated"]["board"][0]["status"] == "in_progress"
    assert events["GuardrailFired"]["guardrail"] == "repeat"
    assert events["UsageRecorded"]["latency_ms"] == 8
    assert events["RunFinished"]["compactions"] == 1


def test_unknown_event_class_raises_instead_of_being_dropped() -> None:
    class Unmapped(DomainEvent):
        pass

    with pytest.raises(TypeError, match="Unmapped"):
        to_record(Unmapped(at=AT))


class TestEventRecorder:
    def test_collects_and_filters(self) -> None:
        recorder = EventRecorder()
        for event in _all_events():
            recorder(event)
        assert len(recorder.events) == len(_all_events())
        assert len(recorder.of_type(RunStarted)) == 1
        assert recorder.of_type(UsageRecorded)[0].model == "m"

    def test_counts(self) -> None:
        recorder = EventRecorder()
        recorder(RunStarted(at=AT, run_id="r", task="t", model="m", policy="p"))
        recorder(RunStarted(at=AT, run_id="r", task="t", model="m", policy="p"))
        recorder(GuardrailFired(at=AT, run_id="r", guardrail="g", detail="d"))
        assert recorder.counts() == {"RunStarted": 2, "GuardrailFired": 1}

    def test_clear(self) -> None:
        recorder = EventRecorder()
        recorder(GuardrailFired(at=AT, run_id="r", guardrail="g", detail="d"))
        recorder.clear()
        assert recorder.events == []


class TestJsonlEventHandler:
    def test_appends_one_line_per_event(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        handler = JsonlEventHandler(path)
        for event in _all_events():
            handler(event)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(_all_events())
        first = json.loads(lines[0])
        assert first["event"] == "RunStarted"

    def test_appends_across_handler_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        JsonlEventHandler(path)(RunStarted(at=AT, run_id="r", task="t", model="m", policy="p"))
        JsonlEventHandler(path)(RunStarted(at=AT, run_id="r", task="t", model="m", policy="p"))
        assert len(path.read_text(encoding="utf-8").splitlines()) == 2

    def test_write_errors_go_to_stderr_not_to_the_caller(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        blocked = tmp_path / "dir"
        blocked.mkdir()  # opening a directory for append fails with IsADirectoryError
        handler = JsonlEventHandler(blocked / "events.jsonl")
        handler._path = blocked
        handler(RunStarted(at=AT, run_id="r", task="t", model="m", policy="p"))
        captured = capsys.readouterr()
        assert "RunStarted" in captured.err

    def test_unmappable_event_is_reported_not_raised(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class Unmapped(DomainEvent):
            pass

        handler = JsonlEventHandler(tmp_path / "events.jsonl")
        handler(Unmapped(at=AT))
        assert "Unmapped" in capsys.readouterr().err


def test_handler_can_subscribe_to_the_domain_bus(tmp_path: Path) -> None:
    from caio_code.domain.events import InMemoryEventBus

    path = tmp_path / "bus.jsonl"
    bus = InMemoryEventBus()
    recorder = EventRecorder()
    bus.subscribe(recorder)
    bus.subscribe(JsonlEventHandler(path))
    bus.publish(RunStarted(at=AT, run_id="r", task="t", model="m", policy="p"))
    assert len(recorder.events) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["event"] == "RunStarted"


def test_clock_injection_keeps_timestamps_deterministic() -> None:
    clock = FixedClock(AT, step_ms=0)
    event = RunStarted(at=clock.now(), run_id="r", task="t", model="m", policy="p")
    assert to_record(event)["at"] == AT.isoformat()
