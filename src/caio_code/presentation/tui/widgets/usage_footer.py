"""The context/usage footer: model, policy, context fill, tokens, cache, cost.

All numbers are formatted here, in one place, so the driver's
``AssertFooter(contains=...)`` can rely on stable text:

``stub · none · ctx 12.4k / 8.0k (155%) OVER BUDGET · in 1.2k out 340 · cache 42% · $0.0123 · running``
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal

from textual.widgets import Static

from caio_code.presentation.tui.theme import USAGE_FOOTER_ID

KILO = 1_000
TOKEN_DECIMALS = 1
PROGRESS_SCALE = 100
COST_DECIMALS = 4
SEPARATOR = " · "
OVER_BUDGET_LABEL = "OVER BUDGET"
UNKNOWN_VALUE = "-"

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_COMPACTING = "compacting"
STATUS_INTERRUPTED = "interrupted"
STATUS_FINISHED = "finished"
STATUS_ERROR = "error"


def format_token_count(tokens: int) -> str:
    """``850`` stays ``850``; ``12_400`` becomes ``12.4k``."""
    if tokens < KILO:
        return str(tokens)
    return f"{tokens / KILO:.{TOKEN_DECIMALS}f}k"


def format_percent(ratio: float) -> str:
    return f"{round(ratio * PROGRESS_SCALE)}%"


def format_cost(usd: Decimal) -> str:
    return f"${usd:.{COST_DECIMALS}f}"


@dataclass(frozen=True, slots=True)
class FooterState:
    """Everything the footer shows; the widget is a pure function of it."""

    model: str = UNKNOWN_VALUE
    policy: str = UNKNOWN_VALUE
    used_tokens: int | None = None
    budget_tokens: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hit_ratio: float | None = None
    cost_usd: Decimal = Decimal(0)
    status: str = STATUS_IDLE

    @property
    def over_budget(self) -> bool:
        return (
            self.used_tokens is not None
            and self.budget_tokens is not None
            and self.used_tokens > self.budget_tokens
        )

    def context_part(self) -> str:
        if self.used_tokens is None or self.budget_tokens is None or self.budget_tokens <= 0:
            return f"ctx {UNKNOWN_VALUE}"
        ratio = self.used_tokens / self.budget_tokens
        fill = (
            f"ctx {format_token_count(self.used_tokens)} / "
            f"{format_token_count(self.budget_tokens)} ({format_percent(ratio)})"
        )
        if self.over_budget:
            fill = f"{fill} {OVER_BUDGET_LABEL}"
        return fill

    def render(self) -> str:
        cache = (
            UNKNOWN_VALUE if self.cache_hit_ratio is None else format_percent(self.cache_hit_ratio)
        )
        return SEPARATOR.join(
            (
                self.model,
                self.policy,
                self.context_part(),
                f"in {format_token_count(self.input_tokens)} "
                f"out {format_token_count(self.output_tokens)}",
                f"cache {cache}",
                format_cost(self.cost_usd),
                self.status,
            )
        )


class UsageFooter(Static):
    """Renders :class:`FooterState`; callers only push state changes."""

    def __init__(self, state: FooterState | None = None) -> None:
        self._state = state or FooterState()
        super().__init__(self._state.render(), id=USAGE_FOOTER_ID, markup=False)
        self.set_class(self._state.over_budget, "over-budget")

    @property
    def state(self) -> FooterState:
        return self._state

    @property
    def text(self) -> str:
        return str(self.content)

    def update_state(self, **changes: object) -> None:
        """Replace fields of the state and re-render."""
        self._state = replace(self._state, **changes)  # type: ignore[arg-type]
        self.update(self._state.render())
        self.set_class(self._state.over_budget, "over-budget")

    def full_text(self) -> str:
        return self.text
