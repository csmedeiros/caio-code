"""Offline tests for the run ledger built from the event stream."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from caio_code.application.metrics.ledger import RunLedger
from caio_code.config import ModelPrice
from caio_code.domain.events import (
    CompactionEnded,
    InMemoryEventBus,
    MessageAppended,
    ToolCallCompleted,
    UsageRecorded,
)
from caio_code.domain.usage.accounting import Cost, PriceSheet, TokenUsage

START = datetime(2026, 1, 1, tzinfo=UTC)
PRICE = ModelPrice("m", Decimal("2"), Decimal("1"), Decimal("4"))
PRICING = PriceSheet(prices=(PRICE,))


def _ledger() -> tuple[RunLedger, InMemoryEventBus]:
    bus = InMemoryEventBus()
    return RunLedger(bus, PRICING, "m"), bus


def _usage_event(usage: TokenUsage, model: str = "m") -> UsageRecorded:
    return UsageRecorded(
        at=START,
        run_id="run-1",
        usage=usage,
        cost=Cost.zero(),
        model=model,
    )


def test_usage_events_accumulate_into_accounting_with_the_price_sheet() -> None:
    ledger, bus = _ledger()

    bus.publish(_usage_event(TokenUsage(input_tokens=1_000_000, output_tokens=0)))
    bus.publish(_usage_event(TokenUsage(input_tokens=500_000, output_tokens=10)))

    accounting = ledger.accounting()
    assert accounting.usage.input_tokens == 1_500_000
    assert accounting.usage.output_tokens == 10
    assert accounting.usage.cached_input_tokens == 0
    # 1.5M input at $2/M plus 10 output at $4/M.
    assert accounting.cost.usd == Decimal("3.00004")
    assert accounting.model == "m"
    assert ledger.calls == 2


def test_cache_hit_ratio_comes_from_the_recorded_usages() -> None:
    ledger, bus = _ledger()

    bus.publish(_usage_event(TokenUsage(input_tokens=100, cached_input_tokens=50)))
    bus.publish(_usage_event(TokenUsage(input_tokens=100, cached_input_tokens=0)))

    accounting = ledger.accounting()
    assert accounting.usage.cached_input_tokens == 50
    assert accounting.cache.hit_ratio == 0.25
    assert accounting.cache.call_hit_ratio == 0.5


def test_compaction_ended_increments_compactions() -> None:
    ledger, bus = _ledger()

    bus.publish(
        CompactionEnded(
            at=START,
            run_id="run-1",
            summary_chars=10,
            sections=5,
            well_formed=True,
            usage=TokenUsage(),
            cost=Cost.zero(),
            latency_ms=1,
        )
    )

    assert ledger.compactions == 1


def test_only_truncated_tool_calls_count_as_truncated_outputs() -> None:
    ledger, bus = _ledger()

    bus.publish(
        ToolCallCompleted(
            at=START, run_id="run-1", tool="read", call_id="c1", chars=10, truncated=True
        )
    )
    bus.publish(
        ToolCallCompleted(
            at=START, run_id="run-1", tool="read", call_id="c2", chars=10, truncated=False
        )
    )

    assert ledger.tool_calls == 2
    assert ledger.truncated_tool_outputs == 1


def test_record_works_without_the_bus() -> None:
    ledger, _ = _ledger()

    ledger.record(TokenUsage(input_tokens=1_000_000))

    assert ledger.calls == 1
    assert ledger.accounting().usage.input_tokens == 1_000_000
    assert ledger.accounting().cost.usd == Decimal("2")


def test_reset_clears_everything_but_keeps_the_model_name() -> None:
    ledger, bus = _ledger()
    bus.publish(_usage_event(TokenUsage(input_tokens=10)))
    bus.publish(
        ToolCallCompleted(
            at=START, run_id="run-1", tool="read", call_id="c1", chars=1, truncated=True
        )
    )

    ledger.reset()

    assert ledger.calls == 0
    assert ledger.compactions == 0
    assert ledger.truncated_tool_outputs == 0
    assert ledger.tool_calls == 0
    assert ledger.accounting().usage.total_tokens == 0
    assert ledger.accounting().model == "m"


def test_proxy_error_ratio_compares_proxy_prediction_with_provider_count() -> None:
    ledger, _ = _ledger()

    ledger.record(TokenUsage(input_tokens=100), proxy_input_tokens=120)

    assert ledger.accounting().proxy_error_ratio == 0.2


def test_unrelated_events_do_not_change_the_ledger() -> None:
    ledger, bus = _ledger()

    bus.publish(
        MessageAppended(
            at=START, run_id="run-1", message_id="m1", role="user", chars=3, preview="hi"
        )
    )

    assert ledger.calls == 0
    assert ledger.accounting().usage.total_tokens == 0
