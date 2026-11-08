"""Cost, cache and token accounting as value objects.

Chapter 4 reports three numbers per arm besides accuracy: tokens, cache hit
ratio and cost. They are computed here, in the domain, so every arm is measured
with the same arithmetic instead of each script doing its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from caio_code.config import FALLBACK_PRICE, PRICE_SHEET, ModelPrice
from caio_code.domain.errors import CaioCodeError

TOKENS_PER_MILLION = Decimal(1_000_000)
CENTS = Decimal("0.000001")


class PricingError(CaioCodeError):
    """A price sheet entry is unusable."""


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Tokens a single model call consumed, as the provider reported them."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("cached_input_tokens", self.cached_input_tokens),
        ):
            if value < 0:
                msg = f"{name} must be non-negative, got {value}"
                raise ValueError(msg)
        if self.cached_input_tokens > self.input_tokens:
            msg = (
                f"cached_input_tokens {self.cached_input_tokens} exceeds "
                f"input_tokens {self.input_tokens}"
            )
            raise ValueError(msg)

    @property
    def uncached_input_tokens(self) -> int:
        return self.input_tokens - self.cached_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
        )


@dataclass(frozen=True, slots=True)
class CacheStats:
    """Prompt-cache behaviour across the calls of one run."""

    calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    calls_with_cache_hit: int = 0

    @property
    def hit_ratio(self) -> float:
        """Fraction of prompt tokens served from cache, in [0, 1]."""
        if self.input_tokens <= 0:
            return 0.0
        return self.cached_input_tokens / self.input_tokens

    @property
    def call_hit_ratio(self) -> float:
        if self.calls <= 0:
            return 0.0
        return self.calls_with_cache_hit / self.calls

    @classmethod
    def from_usages(cls, usages: Iterable[TokenUsage]) -> CacheStats:
        calls = 0
        input_tokens = 0
        cached = 0
        hits = 0
        for usage in usages:
            calls += 1
            input_tokens += usage.input_tokens
            cached += usage.cached_input_tokens
            if usage.cached_input_tokens > 0:
                hits += 1
        return cls(
            calls=calls,
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            calls_with_cache_hit=hits,
        )


@dataclass(frozen=True, slots=True)
class Cost:
    """USD, kept in Decimal because floats accumulate visibly over 100 runs."""

    usd: Decimal

    @classmethod
    def zero(cls) -> Cost:
        return cls(Decimal("0"))

    def __post_init__(self) -> None:
        if self.usd < 0:
            msg = f"cost must be non-negative, got {self.usd}"
            raise ValueError(msg)

    def __add__(self, other: Cost) -> Cost:
        return Cost(self.usd + other.usd)

    @property
    def rounded(self) -> Decimal:
        return self.usd.quantize(CENTS, rounding=ROUND_HALF_UP)

    def as_float(self) -> float:
        return float(self.rounded)


@dataclass(frozen=True, slots=True)
class PriceSheet:
    """Model -> price. Unknown models fall back to a conservative estimate."""

    prices: Sequence[ModelPrice] = PRICE_SHEET
    fallback: ModelPrice = FALLBACK_PRICE

    def for_model(self, model: str) -> ModelPrice:
        normalized = model.split(":", 1)[-1].strip()
        for price in self.prices:
            if price.model == normalized:
                return price
        for price in self.prices:
            if normalized.startswith(price.model) or price.model.startswith(normalized):
                return price
        return self.fallback

    def cost_of(self, usage: TokenUsage, model: str) -> Cost:
        price = self.for_model(model)
        cached = Decimal(usage.cached_input_tokens)
        uncached = Decimal(usage.uncached_input_tokens)
        output = Decimal(usage.output_tokens)
        total = (
            uncached * price.input_per_million
            + cached * price.cached_input_per_million
            + output * price.output_per_million
        )
        if total < 0:
            msg = f"negative cost computed for {model}: {total}"
            raise PricingError(msg)
        return Cost(total / TOKENS_PER_MILLION)


@dataclass(frozen=True, slots=True)
class RunAccounting:
    """Everything one run cost, ready to be aggregated per arm."""

    usage: TokenUsage
    cache: CacheStats
    cost: Cost
    model: str
    proxy_input_tokens: int = 0
    """Tokens the char-proxy predicted, to compare against the provider's count."""

    @property
    def proxy_error_ratio(self) -> float:
        if self.usage.input_tokens <= 0:
            return 0.0
        return abs(self.proxy_input_tokens - self.usage.input_tokens) / self.usage.input_tokens


@dataclass(slots=True)
class UsageLedger:
    """Accumulates accounting across the calls of a run or of an experiment."""

    model: str = "stub"
    usages: list[TokenUsage] = field(default_factory=list)
    costs: list[Cost] = field(default_factory=list)
    proxy_input_tokens: int = 0

    def record(self, usage: TokenUsage, *, cost: Cost, proxy_input_tokens: int = 0) -> None:
        self.usages.append(usage)
        self.costs.append(cost)
        self.proxy_input_tokens += proxy_input_tokens

    @property
    def calls(self) -> int:
        return len(self.usages)

    def total_usage(self) -> TokenUsage:
        total = TokenUsage()
        for usage in self.usages:
            total = total + usage
        return total

    def total_cost(self) -> Cost:
        total = Cost.zero()
        for cost in self.costs:
            total = total + cost
        return total

    def accounting(self) -> RunAccounting:
        return RunAccounting(
            usage=self.total_usage(),
            cache=CacheStats.from_usages(self.usages),
            cost=self.total_cost(),
            model=self.model,
            proxy_input_tokens=self.proxy_input_tokens,
        )
