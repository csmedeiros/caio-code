"""Pricing helpers: the bridge between provider usage and the domain ledger.

No price is defined here. The numbers live in ``config.PRICE_SHEET`` and
``config.FALLBACK_PRICE``; this module only assembles the domain objects
(:class:`PriceSheet`, :class:`Cost`, :class:`RunAccounting`) from them so every
arm of the experiment is priced with the same arithmetic.
"""

from __future__ import annotations

from collections.abc import Iterable

from caio_code.config import FALLBACK_PRICE, PRICE_SHEET, Settings
from caio_code.domain.usage.accounting import (
    CacheStats,
    Cost,
    PriceSheet,
    RunAccounting,
    TokenUsage,
)


def pricing_for(settings: Settings) -> PriceSheet:
    """The price sheet for a run. Settings are accepted for future overrides."""
    return PriceSheet(prices=PRICE_SHEET, fallback=FALLBACK_PRICE)


def cost_of(usage: TokenUsage, model: str, sheet: PriceSheet | None = None) -> Cost:
    """USD cost of one call, priced by ``model`` (fallback when unknown)."""
    resolved = sheet if sheet is not None else PriceSheet(prices=PRICE_SHEET, fallback=FALLBACK_PRICE)
    return resolved.cost_of(usage, model)


def accounting_for(
    usages: Iterable[TokenUsage],
    model: str,
    *,
    proxy_input_tokens: int = 0,
    sheet: PriceSheet | None = None,
) -> RunAccounting:
    """Aggregate every call of a run into tokens, cache stats and cost."""
    resolved = sheet if sheet is not None else PriceSheet(prices=PRICE_SHEET, fallback=FALLBACK_PRICE)
    materialized = list(usages)
    total = TokenUsage()
    for usage in materialized:
        total = total + usage
    return RunAccounting(
        usage=total,
        cache=CacheStats.from_usages(materialized),
        cost=sum(
            (resolved.cost_of(usage, model) for usage in materialized),
            Cost.zero(),
        ),
        model=model,
        proxy_input_tokens=proxy_input_tokens,
    )
