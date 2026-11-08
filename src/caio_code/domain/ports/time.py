"""Time and identity ports.

``datetime.now`` and ``uuid4`` are banned from the agent path: a run that cannot
be replayed cannot be reported. Callers inject these instead, and tests inject
fixed ones.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Current time, injected."""

    def now(self) -> datetime:
        """Timezone-aware current instant."""

    def monotonic_ms(self) -> int:
        """Monotonic milliseconds, for latency measurement only."""


@runtime_checkable
class IdentifierFactory(Protocol):
    """Identifiers for messages, runs and trials, injected."""

    def message_id(self) -> str:
        """A new message identifier."""

    def run_id(self) -> str:
        """A new run identifier."""

    def trial_id(self) -> str:
        """A new trial identifier."""
