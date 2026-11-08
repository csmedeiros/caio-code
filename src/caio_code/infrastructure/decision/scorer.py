"""Relevance scorer backed by the decision model: one Noul per message.

The message-selection policy needs a relevance score per message. Instead of
asking a chat model to emit JSON numbers (``ModelRelevanceScorer``), this scorer
asks the decision model one yes/no question per message - "will the agent need
this later?" - and uses the probability of yes, which is exactly the calibrated
number the policy wants.

Cost discipline (ADR 0005): the whole state is resent with every request, so

- each message text is capped at ``DecisionConfig.state_message_char_cap``
  (relevance does not need a 2,000-line file dump), and
- questions are batched at ``DecisionConfig.questions_per_request`` per request,
  with every batch's usage recorded.

A scorer that costs more than the tokens it saves is not a win; the accumulated
usage is handed to the experiment through ``UsageReporting.drain_usage()``.

The scorer is advisory infrastructure inside the agent loop: on ANY provider
error, or on a missing answer for any message, it degrades to the injected
``fallback`` scorer for the whole batch, records the reason in ``last_note`` and
never raises into the loop.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from caio_code.config import DecisionConfig
from caio_code.domain.conversation.messages import Message
from caio_code.domain.errors import CaioCodeError
from caio_code.domain.ports.decision import DecisionModel, NoulQuestion, Question
from caio_code.domain.ports.scorer import RelevanceScorer, ScoredMessage
from caio_code.domain.ports.time import Clock
from caio_code.domain.usage.accounting import TokenUsage

QUESTION_TEMPLATE = (
    "Will the agent need the information in message {message_id} later to complete the task?"
)
TRUE_CRITERIA = (
    "The message carries a fact, constraint, decision, file, error or instruction that is "
    "likely necessary to complete the task described in the state."
)
FALSE_CRITERIA = (
    "The message is noise for the task: superseded tool output, chatter, or content "
    "unrelated to completing the task."
)
TRUNCATION_MARKER = "…[truncated]"


def cap_text(text: str, cap: int) -> str:
    """Cap one message's text, leaving a visible marker when it was cut."""
    if len(text) <= cap:
        return text
    return text[:cap] + TRUNCATION_MARKER


def question_id_for(index: int) -> str:
    """Question id of the message at ``index``; positional so ids never collide."""
    return f"m{index}"


def relevance_question(message: Message) -> NoulQuestion:
    """The per-message Noul question, referencing the message id shown in the state."""
    return NoulQuestion(
        instructions=QUESTION_TEMPLATE.format(message_id=message.id),
        true_criteria=TRUE_CRITERIA,
        false_criteria=FALSE_CRITERIA,
    )


def _batches(total: int, size: int) -> Iterator[range]:
    for start in range(0, total, size):
        yield range(start, min(start + size, total))


class DecisionRelevanceScorer(RelevanceScorer):
    """``RelevanceScorer`` over the decision-model port; degrades to ``fallback``."""

    def __init__(
        self,
        decision_model: DecisionModel,
        *,
        config: DecisionConfig,
        fallback: RelevanceScorer,
        clock: Clock | None = None,
    ) -> None:
        self._decision_model = decision_model
        self._config = config
        self._fallback = fallback
        self._clock = clock
        self._pending_usage: list[TokenUsage] = []
        self.last_note = ""
        """Why the last scoring degraded to the fallback; empty when it did not."""

    @property
    def name(self) -> str:
        return f"decision/{self._decision_model.model}"

    def drain_usage(self) -> tuple[TokenUsage, ...]:
        """Usage of every request since the last drain; the buffer is cleared."""
        drained = tuple(self._pending_usage)
        self._pending_usage.clear()
        return drained

    # ------------------------------------------------------------------
    # State and questions
    # ------------------------------------------------------------------

    def _state(self, task: str, messages: Sequence[Message]) -> dict[str, object]:
        cap = self._config.state_message_char_cap
        return {
            "task": task,
            "messages": [
                {
                    "id": message.id,
                    "role": message.role.value,
                    "text": cap_text(message.text, cap),
                }
                for message in messages
            ],
        }

    def _questions(self, indices: range, messages: Sequence[Message]) -> dict[str, Question]:
        return {
            question_id_for(index): relevance_question(messages[index]) for index in indices
        }

    def _scored(
        self, messages: Sequence[Message], scores: Sequence[float]
    ) -> list[ScoredMessage]:
        return [
            ScoredMessage(index=index, score=score, message=message)
            for index, (message, score) in enumerate(zip(messages, scores, strict=True))
        ]

    def _degrade(
        self,
        note: str,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        self.last_note = note
        return self._fallback.score(task=task, messages=messages)

    async def _adegrade(
        self,
        note: str,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        self.last_note = note
        return await self._fallback.ascore(task=task, messages=messages)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(
        self,
        *,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        self.last_note = ""
        if not messages:
            return []
        state = self._state(task, messages)
        scores: list[float | None] = [None] * len(messages)
        try:
            for batch in _batches(len(messages), self._config.questions_per_request):
                answers = self._decision_model.classify(state, self._questions(batch, messages))
                self._pending_usage.append(answers.usage)
                for index in batch:
                    answer = answers.noul(question_id_for(index))
                    if answer is not None:
                        scores[index] = answer.probability
        except CaioCodeError as exc:
            return self._degrade(
                f"decision scorer degraded to {self._fallback.name}: "
                f"{type(exc).__name__}: {exc}",
                task,
                messages,
            )
        missing = [index for index, score in enumerate(scores) if score is None]
        if missing:
            return self._degrade(
                f"decision scorer degraded to {self._fallback.name}: "
                f"no answer for {len(missing)} of {len(messages)} messages",
                task,
                messages,
            )
        return self._scored(messages, [score if score is not None else 0.0 for score in scores])

    async def ascore(
        self,
        *,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        self.last_note = ""
        if not messages:
            return []
        state = self._state(task, messages)
        scores: list[float | None] = [None] * len(messages)
        try:
            for batch in _batches(len(messages), self._config.questions_per_request):
                answers = await self._decision_model.aclassify(
                    state, self._questions(batch, messages)
                )
                self._pending_usage.append(answers.usage)
                for index in batch:
                    answer = answers.noul(question_id_for(index))
                    if answer is not None:
                        scores[index] = answer.probability
        except CaioCodeError as exc:
            return await self._adegrade(
                f"decision scorer degraded to {self._fallback.name}: "
                f"{type(exc).__name__}: {exc}",
                task,
                messages,
            )
        missing = [index for index, score in enumerate(scores) if score is None]
        if missing:
            return await self._adegrade(
                f"decision scorer degraded to {self._fallback.name}: "
                f"no answer for {len(missing)} of {len(messages)} messages",
                task,
                messages,
            )
        return self._scored(messages, [score if score is not None else 0.0 for score in scores])


__all__ = [
    "QUESTION_TEMPLATE",
    "DecisionRelevanceScorer",
    "cap_text",
    "question_id_for",
    "relevance_question",
]
