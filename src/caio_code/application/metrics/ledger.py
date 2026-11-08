"""Run accounting: what a run cost, accumulated from the event stream.

The ledger subscribes to the bus instead of being called by the runner, so an
arm of the experiment and an interactive session are measured by exactly the
same code. Cost is priced with the domain :class:`PriceSheet`, never recomputed
per call site.
"""

from __future__ import annotations

from caio_code.domain.events import (
    CompactionEnded,
    DomainEvent,
    EventBus,
    ToolCallCompleted,
    UsageRecorded,
)
from caio_code.domain.usage.accounting import PriceSheet, RunAccounting, TokenUsage, UsageLedger


class RunLedger:
    """Accumulates usage, cache and cost for one run."""

    def __init__(self, bus: EventBus, pricing: PriceSheet, model: str) -> None:
        self._ledger = UsageLedger(model=model)
        self._pricing = pricing
        self._calls = 0
        self.compactions = 0
        self.truncated_tool_outputs = 0
        self.tool_calls = 0
        bus.subscribe(self._on_event)

    @property
    def calls(self) -> int:
        return self._calls

    def record(self, usage: TokenUsage, *, model: str | None = None, proxy_input_tokens: int = 0) -> None:
        """Record a call that did not travel through the bus (used by the harness)."""
        effective = model or self._ledger.model
        self._ledger.model = effective
        self._ledger.record(
            usage,
            cost=self._pricing.cost_of(usage, effective),
            proxy_input_tokens=proxy_input_tokens,
        )
        self._calls += 1

    def accounting(self) -> RunAccounting:
        return self._ledger.accounting()

    def reset(self) -> None:
        model = self._ledger.model
        self._ledger = UsageLedger(model=model)
        self._calls = 0
        self.compactions = 0
        self.truncated_tool_outputs = 0
        self.tool_calls = 0

    def _on_event(self, event: DomainEvent) -> None:
        match event:
            case UsageRecorded():
                self._ledger.model = event.model
                self._ledger.record(event.usage, cost=self._pricing.cost_of(event.usage, event.model))
                self._calls += 1
            case CompactionEnded():
                self.compactions += 1
            case ToolCallCompleted():
                self.tool_calls += 1
                if event.truncated:
                    self.truncated_tool_outputs += 1
            case _:
                return
