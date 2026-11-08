"""Clocks and identifier factories.

``datetime.now`` and ``uuid4`` are banned from the agent path (see
``domain/ports/time.py``). This module holds the two sides of that rule:

``SystemClock``
    The real clock. Only the composition root (``cli``/``factory``) may
    instantiate it; every test injects ``FixedClock`` instead.

``FixedClock``
    Deterministic: starts at ``start`` and advances ``step_ms`` milliseconds on
    every reading, so latency measurements in tests are exact and repeatable.

``SequentialIdentifiers``
    Counting identifiers (``prefix-0001``); no ``uuid4`` anywhere.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from caio_code.domain.errors import ConfigurationError
from caio_code.domain.ports.time import Clock, IdentifierFactory

FIXED_CLOCK_STEP_MS = 250
"""Default advance per reading of :class:`FixedClock`."""


class SystemClock(Clock):
    """Real wall clock and monotonic timer. Composition root only."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1_000)


class FixedClock(Clock):
    """Deterministic clock: every reading advances ``step_ms``."""

    def __init__(self, start: datetime, step_ms: int = FIXED_CLOCK_STEP_MS) -> None:
        if step_ms < 0:
            msg = f"step_ms must be non-negative, got {step_ms}"
            raise ConfigurationError(msg)
        if start.tzinfo is None:
            msg = "FixedClock start must be timezone-aware"
            raise ConfigurationError(msg)
        self._start = start
        self._step_ms = step_ms
        self._wall_readings = 0
        self._monotonic_readings = 0

    @property
    def step_ms(self) -> int:
        return self._step_ms

    def now(self) -> datetime:
        instant = self._start + timedelta(milliseconds=self._step_ms * self._wall_readings)
        self._wall_readings += 1
        return instant

    def monotonic_ms(self) -> int:
        value = self._step_ms * self._monotonic_readings
        self._monotonic_readings += 1
        return value


class SequentialIdentifiers(IdentifierFactory):
    """Counting identifiers; deterministic across runs by construction."""

    def __init__(self, prefix: str = "msg") -> None:
        if not prefix.strip():
            msg = "identifier prefix must not be empty"
            raise ConfigurationError(msg)
        self._prefix = prefix
        self._counters = {"msg": 0, "run": 0, "trial": 0}

    def _next(self, kind: str) -> str:
        self._counters[kind] += 1
        return f"{self._prefix}-{kind}-{self._counters[kind]:04d}"

    def message_id(self) -> str:
        return self._next("msg")

    def run_id(self) -> str:
        return self._next("run")

    def trial_id(self) -> str:
        return self._next("trial")
