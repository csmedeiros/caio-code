"""Message selection: keep a non-contiguous, relevance-ordered subset.

Where the sliding window retains a suffix, selection retains whatever scores
highest, which is the only strategy of the four that can keep an early decision
and drop the noise that followed it. Scores come from outside
(:class:`~caio_code.domain.ports.scorer.RelevanceScorer`); the policy itself is
pure and deterministic: greedy by ``(score descending, index ascending)``, with
pinned messages and the most recent ones always retained.
"""

from __future__ import annotations

from caio_code.domain.policy.base import ContextPolicy, PolicyDecision, PolicyRequest, Removal

DEFAULT_SCORE = 0.0


class MessageSelectionPolicy(ContextPolicy):
    """Relevance-scored retention under a token budget."""

    def __init__(
        self,
        *,
        keep_recent_messages: int = 4,
        top_k_floor: int = 1,
        name: str = "message_selection",
    ) -> None:
        if keep_recent_messages < 0:
            msg = f"keep_recent_messages must be non-negative, got {keep_recent_messages}"
            raise ValueError(msg)
        if top_k_floor < 0:
            msg = f"top_k_floor must be non-negative, got {top_k_floor}"
            raise ValueError(msg)
        self._keep_recent = keep_recent_messages
        self._top_k_floor = top_k_floor
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
        scores = self._resolve_scores(request, total)

        pinned = set(transcript.pinned_indices())
        forced = set(range(max(0, total - self._keep_recent), total))
        must_keep = pinned | forced

        accumulated = sum(costs[index] for index in sorted(must_keep))
        selected = set(must_keep)

        # Greedy fill: highest score first, ties broken by chronological order.
        candidates = sorted(
            (index for index in range(total) if index not in must_keep),
            key=lambda index: (-scores[index], index),
        )
        for index in candidates[: max(0, self._top_k_floor)]:
            if index in selected:
                continue
            selected.add(index)
            accumulated += costs[index]
        for index in candidates:
            if index in selected:
                continue
            if accumulated + costs[index] > available:
                continue
            accumulated += costs[index]
            selected.add(index)

        kept_indices = tuple(sorted(selected))
        removals = tuple(
            Removal(index=index, reason=f"relevance {scores[index]:.3f} below the cut")
            for index in range(total)
            if index not in selected
        )
        tokens_after = sum(costs[index] for index in kept_indices) + request.fixed_tokens

        notes: list[str] = []
        if request.scores is None:
            notes.append("no scores supplied: selection degraded to recency")
        if tokens_after > request.budget.tokens:
            notes.append(
                f"selection floor exceeded: retained messages cost {tokens_after} tokens "
                f"against a budget of {request.budget.tokens}"
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
                "messages_kept": len(kept_indices),
                "pinned": sorted(pinned),
                "keep_recent_messages": self._keep_recent,
                "scorer": "supplied" if request.scores is not None else "recency",
                "scores": [round(score, 4) for score in scores],
            },
        )

    def _resolve_scores(self, request: PolicyRequest, total: int) -> list[float]:
        if request.scores is None:
            # Recency fallback: newer messages score higher, deterministically.
            return [float(index) / total if total else DEFAULT_SCORE for index in range(total)]
        if len(request.scores) != total:
            msg = f"expected {total} scores, got {len(request.scores)}"
            raise ValueError(msg)
        return [float(score) for score in request.scores]
