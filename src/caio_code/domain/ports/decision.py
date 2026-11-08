"""Decision-model port: probabilistic judgement instead of text generation.

TypeSafe's Jev is not a language model. It answers typed questions about a state
and returns probabilities: ``Noul`` (probability that a yes/no judgement holds),
``Choice`` (a label with its whole distribution and a confidence) and ``Score``
(an expected position on an ordered rubric). It cannot summarize, cannot write
code and cannot continue a conversation, so it never appears behind the
:class:`~caio_code.domain.ports.gateway.ModelGateway` or
:class:`~caio_code.domain.ports.summarizer.Summarizer` ports.

What it is good for in this agent is exactly what the context policies need: a
calibrated, cheap judgement per message or per tool call. Message selection asks
one ``Noul`` per message - "will the agent need this later?" - and uses the
probability as the relevance score, which is why the port lives next to the
scorer port instead of next to the model gateway.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from caio_code.domain.usage.accounting import TokenUsage

State = str | Mapping[str, object] | Sequence[object]
"""What the decision model judges: text, structured JSON, or chat messages."""


@dataclass(frozen=True, slots=True)
class NoulQuestion:
    """A yes/no judgement, answered with the probability of yes."""

    instructions: str
    true_criteria: str | None = None
    false_criteria: str | None = None


@dataclass(frozen=True, slots=True)
class ChoiceQuestion:
    """One label out of a fixed set, answered with the full distribution."""

    instructions: str
    criteria: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ScoreQuestion:
    """An ordered rubric, answered with an expected (possibly fractional) level."""

    instructions: str
    criteria: Sequence[str]


Question = NoulQuestion | ChoiceQuestion | ScoreQuestion


@dataclass(frozen=True, slots=True)
class NoulAnswer:
    """Probability of yes, in [0, 1]."""

    probability: float


@dataclass(frozen=True, slots=True)
class ChoiceAnswer:
    """Selected label, every label's probability, and the distribution's confidence."""

    choice: str
    probabilities: Mapping[str, float]
    confidence: float


@dataclass(frozen=True, slots=True)
class ScoreAnswer:
    """Expected rubric level, its distribution and its confidence."""

    score: float
    probabilities: Mapping[int, float]
    confidence: float


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


@dataclass(frozen=True, slots=True)
class DecisionAnswers:
    """Everything one classification request returned."""

    model: str
    answers: Mapping[str, Answer]
    usage: TokenUsage
    request_id: str | None = None

    def noul(self, question_id: str) -> NoulAnswer | None:
        answer = self.answers.get(question_id)
        return answer if isinstance(answer, NoulAnswer) else None

    def choice(self, question_id: str) -> ChoiceAnswer | None:
        answer = self.answers.get(question_id)
        return answer if isinstance(answer, ChoiceAnswer) else None

    def score(self, question_id: str) -> ScoreAnswer | None:
        answer = self.answers.get(question_id)
        return answer if isinstance(answer, ScoreAnswer) else None

    def probability_of(self, question_id: str) -> float | None:
        """The single number most callers want, whatever the question type was."""
        answer = self.answers.get(question_id)
        match answer:
            case NoulAnswer(probability=probability):
                return probability
            case ScoreAnswer(score=score):
                return score
            case ChoiceAnswer(confidence=confidence):
                return confidence
            case _:
                return None


@runtime_checkable
class DecisionModel(Protocol):
    """Answers typed questions about a state."""

    model: str

    async def aclassify(
        self, state: State, questions: Mapping[str, Question]
    ) -> DecisionAnswers:
        """Classify asynchronously. Raises ProviderError on transport failure."""

    def classify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        """Classify synchronously."""


@runtime_checkable
class UsageReporting(Protocol):
    """Optional: a collaborator that spent tokens and can hand over the bill.

    A lexical scorer costs nothing and does not implement this. A decision-model
    scorer does, and the experiment adds its usage to the arm it served - an
    arm whose scorer costs more than the tokens it saves is not a win, and the
    report has to show that.
    """

    def drain_usage(self) -> tuple[TokenUsage, ...]:
        """Return the usage recorded since the last drain, and clear it."""
