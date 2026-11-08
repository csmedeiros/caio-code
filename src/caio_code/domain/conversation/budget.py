"""Budgets, limits and the pressure between them."""

from __future__ import annotations

from dataclasses import dataclass

from caio_code.domain.errors import ContextBudgetError


@dataclass(frozen=True, slots=True)
class TokenBudget:
    """How many tokens a shaped context may occupy.

    The budget is compared against the counted cost ``C``, never against a
    message count: a transcript of three messages can cost more than one of
    three hundred.
    """

    tokens: int

    def __post_init__(self) -> None:
        if self.tokens <= 0:
            msg = f"budget must be positive, got {self.tokens}"
            raise ContextBudgetError(msg)

    def minus(self, tokens: int) -> TokenBudget:
        """Budget left after reserving ``tokens``, floored at one token."""
        remaining = self.tokens - tokens
        if remaining <= 0:
            msg = f"fixed cost {tokens} already exhausts the budget of {self.tokens}"
            raise ContextBudgetError(msg)
        return TokenBudget(remaining)


@dataclass(frozen=True, slots=True)
class ContextLimit:
    """What the provider really accepts, apart from the declared window."""

    tokens: int

    def __post_init__(self) -> None:
        if self.tokens <= 0:
            msg = f"context limit must be positive, got {self.tokens}"
            raise ContextBudgetError(msg)


@dataclass(frozen=True, slots=True)
class WindowPressure:
    """Measured relation between what a context costs and what it may cost."""

    used_tokens: int
    limit_tokens: int

    @property
    def overflow_tokens(self) -> int:
        return max(0, self.used_tokens - self.limit_tokens)

    @property
    def over_limit(self) -> bool:
        return self.used_tokens > self.limit_tokens

    @property
    def fill_ratio(self) -> float:
        if self.limit_tokens <= 0:
            return 0.0
        return self.used_tokens / self.limit_tokens

    @property
    def headroom_tokens(self) -> int:
        return max(0, self.limit_tokens - self.used_tokens)
