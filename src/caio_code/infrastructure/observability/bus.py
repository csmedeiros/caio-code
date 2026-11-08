"""Event recording: in-memory collection and JSONL persistence.

``to_record`` serializes every class in ``domain/events.py``; a new event class
without a record mapping is a programming error and raises instead of being
silently dumped as ``{}``.

``JsonlEventHandler`` never raises into the publisher: observability must not be
able to fail an experiment. Write and serialization errors go to stderr.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

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
from caio_code.domain.usage.accounting import Cost, TokenUsage


def _usage_record(usage: TokenUsage) -> dict[str, int]:
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
    }


def _cost_record(cost: Cost) -> str:
    return str(cost.usd)


def to_record(event: DomainEvent) -> dict[str, Any]:
    """Flat, JSON-serializable record of one event. Covers every event class."""
    base: dict[str, Any] = {
        "event": type(event).__name__,
        "at": event.at.isoformat(),
        "run_id": getattr(event, "run_id", None),
    }
    match event:
        case RunStarted():
            base |= {
                "task": event.task,
                "model": event.model,
                "policy": event.policy,
            }
        case MessageAppended():
            base |= {
                "message_id": event.message_id,
                "role": event.role,
                "chars": event.chars,
                "preview": event.preview,
            }
        case ToolCallIssued():
            base |= {
                "tool": event.tool,
                "arguments": event.arguments,
                "call_id": event.call_id,
            }
        case ToolCallCompleted():
            base |= {
                "tool": event.tool,
                "call_id": event.call_id,
                "chars": event.chars,
                "truncated": event.truncated,
                "error": event.error,
            }
        case ContextShaped():
            base |= {"decision": event.record}
        case CompactionStarted():
            base |= {
                "head_chars": event.head_chars,
                "previous_summary": event.previous_summary,
                "reason": event.reason,
            }
        case CompactionEnded():
            base |= {
                "summary_chars": event.summary_chars,
                "sections": event.sections,
                "well_formed": event.well_formed,
                "usage": _usage_record(event.usage),
                "cost_usd": _cost_record(event.cost),
                "latency_ms": event.latency_ms,
                "reason": event.reason,
            }
        case TodoBoardUpdated():
            base |= {"board": event.board.as_records()}
        case GuardrailFired():
            base |= {"guardrail": event.guardrail, "detail": event.detail}
        case UsageRecorded():
            base |= {
                "usage": _usage_record(event.usage),
                "cost_usd": _cost_record(event.cost),
                "model": event.model,
                "latency_ms": event.latency_ms,
            }
        case RunFinished():
            base |= {
                "status": event.status,
                "usage": _usage_record(event.usage),
                "cost_usd": _cost_record(event.cost),
                "compactions": event.compactions,
                "error": event.error,
            }
        case _:
            msg = f"no record mapping for event class {type(event).__name__!r}"
            raise TypeError(msg)
    return base


class EventRecorder:
    """Collects events in memory; the test double for the whole event stream."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def __call__(self, event: DomainEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: type[DomainEvent]) -> list[DomainEvent]:
        return [event for event in self.events if isinstance(event, event_type)]

    def counts(self) -> Counter[str]:
        return Counter(type(event).__name__ for event in self.events)

    def clear(self) -> None:
        self.events.clear()


class JsonlEventHandler:
    """Appends one JSON line per event; write errors go to stderr, never up."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def __call__(self, event: DomainEvent) -> None:
        try:
            record = to_record(event)
            line = json.dumps(record, ensure_ascii=False, default=str)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except (OSError, TypeError, ValueError) as exc:
            print(
                f"JsonlEventHandler: dropped {type(event).__name__}: {exc}",
                file=sys.stderr,
            )
