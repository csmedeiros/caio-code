"""Value objects of one agent run: the context snapshot and the run result.

Both are plain data with a serializable ``as_record()``, so the CLI, the eval
harness and the tests read the same shape. Timestamps come from the injected
:class:`~caio_code.domain.ports.time.Clock`; nothing here reads a wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from caio_code.domain.policy.base import PipelineDecision, PolicyDecision
from caio_code.domain.todo.items import TodoBoard
from caio_code.domain.usage.accounting import RunAccounting

RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_INTERRUPTED = "interrupted"
RUN_STATUS_ERROR = "error"
"""Same literals the TUI facade port documents; kept here so the application
layer never imports presentation."""

RUN_STATUSES: frozenset[str] = frozenset(
    {RUN_STATUS_COMPLETED, RUN_STATUS_INTERRUPTED, RUN_STATUS_ERROR}
)


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """What the last context decision did, in the shape reports consume."""

    policy: str
    tokens_before: int
    tokens_after: int
    budget_tokens: int
    overflow_tokens: int
    kept: int
    dropped: int
    record: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def from_decision(cls, decision: PipelineDecision | PolicyDecision) -> ContextSnapshot:
        """Snapshot from either decision kind; counts come from the record."""
        record = decision.as_record()
        if isinstance(decision, PipelineDecision):
            final = decision.final
            policy = decision.name
            kept = len(final.kept_indices)
            dropped = sum(step.decision.dropped for step in decision.steps)
        else:
            policy = decision.policy
            kept = len(decision.kept_indices)
            dropped = decision.dropped
        return cls(
            policy=policy,
            tokens_before=decision.tokens_before,
            tokens_after=decision.tokens_after,
            budget_tokens=decision.budget_tokens,
            overflow_tokens=decision.overflow_tokens,
            kept=kept,
            dropped=dropped,
            record=dict(record),
        )

    def as_record(self) -> dict[str, Any]:
        """The full decision record, guaranteed to carry the snapshot fields."""
        base = dict(self.record)
        base.update(
            {
                "policy": self.policy,
                "tokens_before": self.tokens_before,
                "tokens_after": self.tokens_after,
                "budget_tokens": self.budget_tokens,
                "overflow_tokens": self.overflow_tokens,
                "kept": self.kept,
                "dropped": self.dropped,
            }
        )
        return base


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Everything one run produced, measured and serialized as one record."""

    run_id: str
    status: str
    final_text: str
    accounting: RunAccounting
    board: TodoBoard
    compactions: int
    latency_ms: int
    started_at: datetime
    finished_at: datetime
    transcript: tuple[dict[str, Any], ...] = ()
    context: ContextSnapshot | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.status not in RUN_STATUSES:
            msg = f"unknown run status {self.status!r}; expected one of {sorted(RUN_STATUSES)}"
            raise ValueError(msg)

    @property
    def completed(self) -> bool:
        return self.status == RUN_STATUS_COMPLETED

    def as_record(self) -> dict[str, Any]:
        usage = self.accounting.usage
        cost = self.accounting.cost
        return {
            "run_id": self.run_id,
            "status": self.status,
            "final_text": self.final_text,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "model": self.accounting.model,
            "usage": {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "total_tokens": usage.total_tokens,
            },
            "cache_hit_ratio": round(self.accounting.cache.hit_ratio, 4),
            "cost_usd": str(cost.rounded),
            "proxy_input_tokens": self.accounting.proxy_input_tokens,
            "compactions": self.compactions,
            "todos": self.board.as_records(),
            "context": self.context.as_record() if self.context is not None else {},
            "transcript": [dict(message) for message in self.transcript],
        }


__all__ = ["AgentRunResult", "ContextSnapshot"]
