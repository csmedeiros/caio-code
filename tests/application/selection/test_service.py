"""Offline tests for the selection use case (scoring seam in front of the policy)."""

from __future__ import annotations

from collections.abc import Sequence

from caio_code.application.selection.service import SelectionService
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.policy.base import PolicyRequest
from caio_code.domain.ports.scorer import RelevanceScorer, ScoredMessage
from caio_code.infrastructure.llm.stub import StubScorer
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

COUNTER = CharProxyTokenCounter()


class FixedScorer:
    """A scorer that returns whatever entries it was built with."""

    def __init__(self, scored: Sequence[ScoredMessage]) -> None:
        self._scored = list(scored)

    @property
    def name(self) -> str:
        return "fixed"

    async def ascore(self, *, task: str, messages: Sequence[Message]) -> Sequence[ScoredMessage]:
        return self._scored

    def score(self, *, task: str, messages: Sequence[Message]) -> Sequence[ScoredMessage]:
        return self._scored


def _transcript(count: int) -> Transcript:
    return Transcript.of(
        Message(id=f"m{i}", role=Role.USER, text=f"message number {i}") for i in range(count)
    )


def _scored(index: int, score: float, message: Message) -> ScoredMessage:
    return ScoredMessage(index=index, score=score, message=message)


def test_stub_scorer_produces_one_score_per_message_and_is_not_degraded() -> None:
    transcript = _transcript(4)
    service = SelectionService(StubScorer())

    outcome = service.score(task="number 2 matters", transcript=transcript)

    assert not outcome.degraded
    assert len(outcome.scores) == len(transcript)
    assert outcome.note == ""


def test_top_indices_sort_by_score_descending_then_index_ascending() -> None:
    transcript = _transcript(4)
    scored = [
        _scored(0, 0.5, transcript[0]),
        _scored(1, 0.9, transcript[1]),
        _scored(2, 0.5, transcript[2]),
        _scored(3, 0.9, transcript[3]),
    ]

    outcome = SelectionService(FixedScorer(scored)).score(task="t", transcript=transcript)

    assert outcome.top_indices == (1, 3, 0, 2)


def test_a_scorer_returning_too_few_scores_degrades_instead_of_raising() -> None:
    transcript = _transcript(3)
    scored = [_scored(0, 0.5, transcript[0]), _scored(1, 0.2, transcript[1])]

    outcome = SelectionService(FixedScorer(scored)).score(task="t", transcript=transcript)

    assert outcome.degraded
    assert outcome.scores == ()
    assert "2 scores for 3 messages" in outcome.note


def test_a_scorer_returning_duplicate_indices_degrades() -> None:
    transcript = _transcript(2)
    scored = [_scored(0, 0.5, transcript[0]), _scored(0, 0.9, transcript[0])]

    outcome = SelectionService(FixedScorer(scored)).score(task="t", transcript=transcript)

    assert outcome.degraded
    assert outcome.scores == ()
    assert "duplicate indices" in outcome.note


async def test_with_scores_returns_a_request_carrying_scores_per_message() -> None:
    transcript = _transcript(3)
    request = PolicyRequest(
        transcript=transcript, budget=TokenBudget(100), counter=COUNTER
    )

    scored_request = await SelectionService(StubScorer()).with_scores(request, task="number 1")

    assert scored_request.scores is not None
    assert len(scored_request.scores) == len(transcript)
    assert scored_request.task == "number 1"


async def test_with_scores_returns_the_original_request_when_scoring_degraded() -> None:
    transcript = _transcript(3)
    request = PolicyRequest(
        transcript=transcript, budget=TokenBudget(100), counter=COUNTER
    )
    service = SelectionService(FixedScorer([_scored(0, 0.5, transcript[0])]))

    scored_request = await service.with_scores(request, task="t")

    assert scored_request is request
    assert scored_request.scores is None


def test_scorer_name_is_exposed() -> None:
    assert SelectionService(StubScorer()).scorer_name == "stub"
    assert isinstance(StubScorer(), RelevanceScorer)
