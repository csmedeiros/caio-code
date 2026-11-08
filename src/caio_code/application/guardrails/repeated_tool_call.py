"""Guardrail: the same tool call, with the same arguments, repeated.

A long-horizon agent that has lost the earlier part of its context re-reads the
same file or re-runs the same failing test forever. The guard is deliberately
narrow - identical name plus identical normalized arguments inside a sliding
window of recent calls - because a wide guard stops legitimate retries. When it
fires it does not abort the run: it publishes the event and hands the runner an
advisory string to return as the tool result, which is the only way the model
learns that the loop was detected.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from caio_code.config import GuardrailConfig
from caio_code.domain.events import EventBus, GuardrailFired
from caio_code.domain.ports.time import Clock

GUARDRAIL_NAME = "repeated_tool_call"
EPOCH = datetime.fromtimestamp(0, tz=UTC)
"""Instant stamped on events when no clock was injected: deterministic, never a read of now()."""
ADVISORY_TEMPLATE = (
    "repeated_tool_call guardrail: this exact {tool} call with the same arguments has now been "
    "made {repeats} times, so the result will not change. Re-read the anchored summary (Next "
    "Move, Relevant Files), try a different command, or report the blocker instead of repeating "
    "the call."
)


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    """What the guard decided about one call."""

    fired: bool
    message: str
    repeats: int

    @property
    def advisory(self) -> str:
        return self.message if self.fired else ""


def normalize_arguments(arguments: str) -> str:
    """Canonical form so key order and whitespace cannot hide a repeat."""
    if not arguments.strip():
        return ""
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return " ".join(arguments.split())
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class RepeatedToolCallGuard:
    """Counts identical calls inside a window and fires at the configured limit."""

    def __init__(
        self,
        config: GuardrailConfig,
        bus: EventBus,
        clock: Clock | None = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._clock = clock
        self._recent: deque[tuple[str, str]] = deque(maxlen=config.window_messages)
        self._firings = 0

    @property
    def firings(self) -> int:
        return self._firings

    @property
    def recent_calls(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._recent)

    def reset(self) -> None:
        self._recent.clear()
        self._firings = 0

    def inspect(self, tool_name: str, arguments: str, *, run_id: str) -> GuardrailVerdict:
        """Record one call and decide whether it is a repeat worth stopping."""
        key = (tool_name, normalize_arguments(arguments))
        repeats = sum(1 for entry in self._recent if entry == key) + 1
        self._recent.append(key)

        if repeats < self._config.max_repeats:
            return GuardrailVerdict(fired=False, message="", repeats=repeats)

        advisory = ADVISORY_TEMPLATE.format(tool=tool_name, repeats=repeats)
        self._firings += 1
        self._bus.publish(
            GuardrailFired(
                at=self._clock.now() if self._clock is not None else EPOCH,
                run_id=run_id,
                guardrail=GUARDRAIL_NAME,
                detail=f"{tool_name} repeated {repeats} times with identical arguments",
            )
        )
        return GuardrailVerdict(fired=True, message=advisory, repeats=repeats)
