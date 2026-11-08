"""Offline tests for clocks and identifier factories."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from caio_code.domain.errors import ConfigurationError
from caio_code.infrastructure.observability.clocks import (
    FIXED_CLOCK_STEP_MS,
    FixedClock,
    SequentialIdentifiers,
    SystemClock,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


class TestSystemClock:
    def test_now_is_timezone_aware(self) -> None:
        assert SystemClock().now().tzinfo is not None

    def test_monotonic_ms_never_goes_backwards(self) -> None:
        clock = SystemClock()
        assert clock.monotonic_ms() <= clock.monotonic_ms()


class TestFixedClock:
    def test_now_advances_by_the_step(self) -> None:
        clock = FixedClock(START, step_ms=100)
        assert clock.now() == START
        assert clock.now() == START + timedelta(milliseconds=100)
        assert clock.now() == START + timedelta(milliseconds=200)

    def test_monotonic_ms_advances_by_the_step(self) -> None:
        clock = FixedClock(START, step_ms=250)
        assert clock.monotonic_ms() == 0
        assert clock.monotonic_ms() == 250
        assert clock.monotonic_ms() == 500

    def test_default_step(self) -> None:
        clock = FixedClock(START)
        assert clock.step_ms == FIXED_CLOCK_STEP_MS
        assert clock.monotonic_ms() == 0
        assert clock.monotonic_ms() == FIXED_CLOCK_STEP_MS

    def test_two_clocks_with_the_same_start_agree(self) -> None:
        first = FixedClock(START, step_ms=10)
        second = FixedClock(START, step_ms=10)
        assert [first.now() for _ in range(3)] == [second.now() for _ in range(3)]

    def test_naive_start_is_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="timezone-aware"):
            FixedClock(datetime(2026, 1, 1))

    def test_negative_step_is_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            FixedClock(START, step_ms=-1)


class TestSequentialIdentifiers:
    def test_message_ids_are_sequential(self) -> None:
        identifiers = SequentialIdentifiers()
        assert identifiers.message_id() == "msg-msg-0001"
        assert identifiers.message_id() == "msg-msg-0002"

    def test_prefix_is_honoured(self) -> None:
        identifiers = SequentialIdentifiers(prefix="exp")
        assert identifiers.message_id().startswith("exp-msg-")
        assert identifiers.run_id().startswith("exp-run-")
        assert identifiers.trial_id().startswith("exp-trial-")

    def test_kinds_have_independent_counters(self) -> None:
        identifiers = SequentialIdentifiers(prefix="x")
        assert identifiers.run_id() == "x-run-0001"
        assert identifiers.message_id() == "x-msg-0001"
        assert identifiers.run_id() == "x-run-0002"

    def test_ids_are_unique(self) -> None:
        identifiers = SequentialIdentifiers()
        ids = {identifiers.message_id() for _ in range(50)}
        assert len(ids) == 50

    def test_empty_prefix_is_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            SequentialIdentifiers(prefix="  ")
