"""Baseline: no management at all.

The control arm of the experiment. It keeps every message and reports the
overflow it produces, which is the quantity Chapter 4 compares the other arms
against. Whether an overflow aborts the run is the caller's decision
(``BaselineConfig.enforce_window``), not the policy's: the policy only measures.
"""

from __future__ import annotations

from caio_code.domain.policy.base import ContextPolicy, PolicyDecision, PolicyRequest


class FullHistoryPolicy(ContextPolicy):
    """Keep everything; report the overflow honestly."""

    def __init__(self, *, name: str = "baseline_full_history") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def plan(self, request: PolicyRequest) -> PolicyDecision:
        costs = request.costs()
        tokens = sum(costs) + request.fixed_tokens
        indices = tuple(range(len(request.transcript)))
        notes: list[str] = []
        if tokens > request.budget.tokens:
            notes.append(
                f"no management: context costs {tokens} tokens against a budget of "
                f"{request.budget.tokens}"
            )
        return PolicyDecision(
            policy=self._name,
            kept_indices=indices,
            counter=request.counter,
            tokens_before=tokens,
            tokens_after=tokens,
            budget_tokens=request.budget.tokens,
            notes=tuple(notes),
            detail={"messages_kept": len(indices), "fixed_tokens": request.fixed_tokens},
        )
