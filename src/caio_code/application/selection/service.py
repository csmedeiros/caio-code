"""Selection use case: turn a task into per-message relevance scores.

The domain policy stays pure and receives scores; producing them is an
infrastructure concern (a lexical scorer offline, an auxiliary model call in
production). This service is the seam: it scores, validates the length, and
returns a request the policy can consume, degrading to "no scores" - which the
policy answers with recency - instead of raising into the agent loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from caio_code.domain.conversation.messages import Transcript
from caio_code.domain.policy.base import PolicyRequest
from caio_code.domain.ports.decision import UsageReporting
from caio_code.domain.ports.scorer import RelevanceScorer, ScoredMessage
from caio_code.domain.usage.accounting import TokenUsage


@dataclass(frozen=True, slots=True)
class ScoringOutcome:
    """Scores, why they look the way they do, and what producing them cost.

    ``usages`` is empty for a lexical scorer and carries one entry per
    decision-model request otherwise. The experiment adds it to the arm's bill:
    a scorer that costs more than the tokens it saves is not a win, and the
    report has to show that.
    """

    scores: tuple[float, ...]
    scorer: str
    degraded: bool
    note: str = ""
    usages: tuple[TokenUsage, ...] = ()

    @property
    def top_indices(self) -> tuple[int, ...]:
        """Most relevant first, ties broken by chronological order."""
        return tuple(
            sorted(range(len(self.scores)), key=lambda index: (-self.scores[index], index))
        )


class SelectionService:
    """Scores a transcript against the current task.

    ``threshold`` demotes messages the scorer considers irrelevant: their score
    becomes zero, so the greedy policy only keeps them when budget is left over
    after every message above the threshold. Without it a long transcript fills
    the window with weakly relevant messages in scorer order.
    """

    def __init__(self, scorer: RelevanceScorer, *, threshold: float | None = None) -> None:
        if threshold is not None and not 0.0 <= threshold <= 1.0:
            msg = f"threshold must be within [0, 1], got {threshold}"
            raise ValueError(msg)
        self._scorer = scorer
        self._threshold = threshold
        self.last_outcome: ScoringOutcome | None = None

    @property
    def scorer_name(self) -> str:
        return self._scorer.name

    @property
    def threshold(self) -> float | None:
        return self._threshold

    def drain_usage(self) -> tuple[TokenUsage, ...]:
        """Usage the scorer recorded, or an empty tuple when it reports none.

        Draining empties the scorer's buffer, so callers that also read
        ``last_outcome.usages`` must pick one of the two: :meth:`ascore` already
        drains into the outcome, and a second drain here returns nothing.
        """
        if isinstance(self._scorer, UsageReporting):
            return self._scorer.drain_usage()
        reporter = getattr(self._scorer, "drain_usage", None)
        if callable(reporter):
            return tuple(reporter())
        return ()

    async def ascore(self, *, task: str, transcript: Transcript) -> ScoringOutcome:
        scored = await self._scorer.ascore(task=task, messages=transcript.messages)
        return self._outcome(scored, transcript, usages=self.drain_usage())

    def score(self, *, task: str, transcript: Transcript) -> ScoringOutcome:
        scored = self._scorer.score(task=task, messages=transcript.messages)
        return self._outcome(scored, transcript, usages=self.drain_usage())

    async def with_scores(self, request: PolicyRequest, *, task: str) -> PolicyRequest:
        """A copy of ``request`` carrying scores, ready for the selection policy."""
        outcome = await self.ascore(task=task, transcript=request.transcript)
        self.last_outcome = outcome
        if outcome.degraded:
            return request
        return PolicyRequest(
            transcript=request.transcript,
            budget=request.budget,
            counter=request.counter,
            fixed_tokens=request.fixed_tokens,
            task=task,
            scores=outcome.scores,
            previous_summary=request.previous_summary,
            tool_result_char_cap=request.tool_result_char_cap,
        )

    def _outcome(
        self, scored, transcript: Transcript, *, usages: tuple[TokenUsage, ...] = ()
    ) -> ScoringOutcome:
        expected = len(transcript)
        items: list[ScoredMessage] = list(scored)
        if len(items) != expected:
            return ScoringOutcome(
                scores=(),
                scorer=self._scorer.name,
                degraded=True,
                note=f"scorer returned {len(items)} scores for {expected} messages",
            )
        by_index = {item.index: float(item.score) for item in items}
        if len(by_index) != expected:
            return ScoringOutcome(
                scores=(),
                scorer=self._scorer.name,
                degraded=True,
                note="scorer returned duplicate indices",
            )
        raw = [by_index[index] for index in range(expected)]
        scores = self._apply_threshold(raw)
        demoted = sum(1 for value, kept in zip(raw, scores, strict=True) if value != kept)
        note = f"{demoted} messages demoted below threshold {self._threshold}" if demoted else ""
        return ScoringOutcome(
            scores=tuple(scores),
            scorer=self._scorer.name,
            degraded=False,
            note=note,
            usages=usages,
        )

    def _apply_threshold(self, scores: Sequence[float]) -> list[float]:
        if self._threshold is None:
            return list(scores)
        return [score if score >= self._threshold else 0.0 for score in scores]
