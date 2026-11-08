"""Sliding window: keep the newest contiguous tail that fits.

The unit of removal is the message, the retained set is always a suffix (plus
whatever is pinned), and the walk is backwards and cumulative: a message joins
the tail only if the tail plus it still fits. One message larger than the whole
budget therefore stays alone in the window rather than being silently cut.
"""

from __future__ import annotations

from caio_code.domain.policy.base import ContextPolicy, PolicyDecision, PolicyRequest, Removal


class SlidingWindowPolicy(ContextPolicy):
    """Suffix retention under a token budget."""

    def __init__(
        self,
        *,
        keep_recent_messages: int = 2,
        name: str = "sliding_window",
    ) -> None:
        if keep_recent_messages < 0:
            msg = f"keep_recent_messages must be non-negative, got {keep_recent_messages}"
            raise ValueError(msg)
        self._keep_recent = keep_recent_messages
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def plan(self, request: PolicyRequest) -> PolicyDecision:
        transcript = request.transcript
        costs = request.costs()
        tokens_before = sum(costs) + request.fixed_tokens
        available = request.available_tokens
        total = len(transcript)

        pinned = set(transcript.pinned_indices())
        forced = set(range(max(0, total - self._keep_recent), total))
        must_keep = pinned | forced

        # Walk backwards, accumulating cost, until the next message does not fit.
        boundary = total
        accumulated = sum(costs[index] for index in sorted(must_keep))
        for index in range(total - 1, -1, -1):
            if index in must_keep:
                boundary = min(boundary, index)
                continue
            if accumulated + costs[index] > available:
                break
            accumulated += costs[index]
            boundary = index

        kept = {index for index in range(boundary, total)} | must_keep
        kept_indices = tuple(sorted(kept))
        removals = tuple(
            Removal(index=index, reason="outside the sliding window")
            for index in range(total)
            if index not in kept
        )
        tokens_after = sum(costs[index] for index in kept_indices) + request.fixed_tokens

        notes: list[str] = []
        if tokens_after > request.budget.tokens:
            notes.append(
                f"window floor exceeded: pinned and forced-recent messages alone cost "
                f"{tokens_after} tokens against a budget of {request.budget.tokens}"
            )

        return PolicyDecision(
            policy=self._name,
            kept_indices=kept_indices,
            counter=request.counter,
            removals=removals,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            budget_tokens=request.budget.tokens,
            notes=tuple(notes),
            detail={
                "boundary": boundary,
                "messages_kept": len(kept_indices),
                "pinned": sorted(pinned),
                "keep_recent_messages": self._keep_recent,
            },
        )
