"""Offline tests for the pricing adapters."""

from __future__ import annotations

from decimal import Decimal

import pytest

from caio_code.config import FALLBACK_PRICE, PRICE_SHEET, Settings
from caio_code.domain.usage.accounting import Cost, RunAccounting, TokenUsage
from caio_code.infrastructure.pricing import accounting_for, cost_of, pricing_for


def test_pricing_for_reuses_the_config_numbers() -> None:
    sheet = pricing_for(Settings())
    assert tuple(sheet.prices) == PRICE_SHEET
    assert sheet.fallback == FALLBACK_PRICE


def test_cost_of_known_model() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    cost = cost_of(usage, "qwen3.8-max")
    assert cost.usd == Decimal("1.60")


def test_cost_of_splits_cached_and_uncached() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0, cached_input_tokens=500_000)
    # 500k uncached at 1.60 + 500k cached at 0.64 = 0.80 + 0.32
    assert cost_of(usage, "qwen3.8-max").usd == Decimal("1.12")


def test_cost_of_output_tokens() -> None:
    usage = TokenUsage(input_tokens=0, output_tokens=1_000_000)
    assert cost_of(usage, "qwen3.8-max").usd == Decimal("6.40")


def test_cost_of_unknown_model_falls_back() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    assert cost_of(usage, "no-such-model").usd == FALLBACK_PRICE.input_per_million


def test_cost_of_zero_usage_is_zero() -> None:
    assert cost_of(TokenUsage(), "qwen3.8-max") == Cost.zero()


def test_cost_of_accepts_an_explicit_sheet() -> None:
    sheet = pricing_for(Settings())
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=0)
    assert cost_of(usage, "qwen3.8-flash", sheet=sheet).usd == Decimal("0.15")


def test_accounting_for_aggregates_usage_cache_and_cost() -> None:
    usages = [
        TokenUsage(input_tokens=100, output_tokens=10, cached_input_tokens=0),
        TokenUsage(input_tokens=100, output_tokens=10, cached_input_tokens=50),
    ]
    accounting = accounting_for(usages, "qwen3.8-max")
    assert isinstance(accounting, RunAccounting)
    assert accounting.usage.input_tokens == 200
    assert accounting.usage.output_tokens == 20
    assert accounting.cache.calls == 2
    assert accounting.cache.calls_with_cache_hit == 1
    assert accounting.cache.hit_ratio == pytest.approx(0.25)
    expected = cost_of(usages[0], "qwen3.8-max") + cost_of(usages[1], "qwen3.8-max")
    assert accounting.cost.usd == expected.usd
    assert accounting.model == "qwen3.8-max"


def test_accounting_for_empty_run_is_zero() -> None:
    accounting = accounting_for([], "stub")
    assert accounting.usage.total_tokens == 0
    assert accounting.cost == Cost.zero()
    assert accounting.cache.hit_ratio == 0.0


def test_accounting_for_reports_proxy_error() -> None:
    usages = [TokenUsage(input_tokens=100, output_tokens=0)]
    accounting = accounting_for(usages, "qwen3.8-max", proxy_input_tokens=80)
    assert accounting.proxy_input_tokens == 80
    assert accounting.proxy_error_ratio == pytest.approx(0.2)
