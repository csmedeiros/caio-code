"""Offline tests for the decision-backed relevance scorer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import pytest

from caio_code.config import DecisionConfig
from caio_code.domain.conversation.messages import Message, Role
from caio_code.domain.errors import ProviderError
from caio_code.domain.ports.decision import (
    DecisionAnswers,
    DecisionModel,
    NoulAnswer,
    Question,
    State,
)
from caio_code.domain.ports.scorer import RelevanceScorer
from caio_code.domain.usage.accounting import TokenUsage
from caio_code.infrastructure.decision.scorer import (
    TRUNCATION_MARKER,
    DecisionRelevanceScorer,
    cap_text,
    question_id_for,
)
from caio_code.infrastructure.decision.stub import StubDecisionModel
from caio_code.infrastructure.llm.stub import StubScorer

TASK = "fix the failing compaction test"


def _messages(count: int, *, text: str = "message text") -> list[Message]:
    return [
        Message(id=f"msg-{index:03d}", role=Role.USER, text=f"{text} {index}")
        for index in range(count)
    ]


class RecordingDecisionModel:
    """A DecisionModel double that records every request and answers every question."""

    def __init__(
        self,
        *,
        probability: float = 0.75,
        usage: TokenUsage | None = None,
        fail_with: ProviderError | None = None,
        drop_answers: bool = False,
    ) -> None:
        self.model = "recording-jev"
        self.states: list[State] = []
        self.questions: list[Mapping[str, Question]] = []
        self._probability = probability
        self._usage = usage or TokenUsage(input_tokens=10, output_tokens=2)
        self._fail_with = fail_with
        self._drop_answers = drop_answers

    @property
    def requests(self) -> int:
        return len(self.states)

    def classify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        self.states.append(state)
        self.questions.append(dict(questions))
        if self._fail_with is not None:
            raise self._fail_with
        answers = (
            {}
            if self._drop_answers
            else {name: NoulAnswer(probability=self._probability) for name in questions}
        )
        return DecisionAnswers(model=self.model, answers=answers, usage=self._usage)

    async def aclassify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        return self.classify(state, questions)


def _scorer(
    decision_model: DecisionModel,
    *,
    config: DecisionConfig | None = None,
    fallback: RelevanceScorer | None = None,
) -> DecisionRelevanceScorer:
    return DecisionRelevanceScorer(
        decision_model,
        config=config or DecisionConfig(),
        fallback=fallback or StubScorer(),
    )


def test_scorer_implements_both_ports() -> None:
    scorer = _scorer(StubDecisionModel())
    assert isinstance(scorer, RelevanceScorer)
    assert hasattr(scorer, "drain_usage")
    assert scorer.name == "decision/stub"


def test_one_score_per_message_in_input_order() -> None:
    messages = _messages(5)
    scored = _scorer(RecordingDecisionModel(probability=0.42)).score(
        task=TASK, messages=messages
    )
    assert [item.index for item in scored] == [0, 1, 2, 3, 4]
    assert [item.message.id for item in scored] == [message.id for message in messages]
    assert all(item.score == pytest.approx(0.42) for item in scored)


async def test_async_path_matches_the_sync_one() -> None:
    messages = _messages(3)
    scorer = _scorer(RecordingDecisionModel(probability=0.42))
    scored = await scorer.ascore(task=TASK, messages=messages)
    assert [item.index for item in scored] == [0, 1, 2]
    assert all(item.score == pytest.approx(0.42) for item in scored)


def test_state_carries_task_and_capped_messages() -> None:
    config = DecisionConfig(state_message_char_cap=20)
    long_text = "x" * 60
    messages = [Message(id="m1", role=Role.USER, text=long_text)]
    model = RecordingDecisionModel()
    _scorer(model, config=config).score(task=TASK, messages=messages)
    state = model.states[0]
    assert isinstance(state, dict)
    assert state["task"] == TASK
    entry = state["messages"][0]  # type: ignore[index]
    assert entry == {"id": "m1", "role": "user", "text": cap_text(long_text, 20)}
    assert entry["text"].endswith(TRUNCATION_MARKER)
    assert len(entry["text"]) == 20 + len(TRUNCATION_MARKER)


def test_one_noul_question_per_message_named_after_the_position() -> None:
    messages = _messages(3)
    model = RecordingDecisionModel()
    _scorer(model).score(task=TASK, messages=messages)
    questions = model.questions[0]
    assert set(questions) == {question_id_for(index) for index in range(3)}
    instruction = str(questions[question_id_for(1)].instructions)
    assert "msg-001" in instruction


def test_batches_at_questions_per_request() -> None:
    messages = _messages(90)
    model = RecordingDecisionModel()
    scored = _scorer(model, config=DecisionConfig(questions_per_request=40)).score(
        task=TASK, messages=messages
    )
    assert model.requests == 3
    assert [len(batch) for batch in model.questions] == [40, 40, 10]
    assert len(scored) == 90
    # The whole state is resent with every batch.
    assert model.states[0] == model.states[1] == model.states[2]


def test_usage_accumulates_across_batches_and_drain_empties_the_buffer() -> None:
    messages = _messages(90)
    usage = TokenUsage(input_tokens=10, output_tokens=2)
    scorer = _scorer(
        RecordingDecisionModel(usage=usage),
        config=DecisionConfig(questions_per_request=40),
    )
    scorer.score(task=TASK, messages=messages)
    drained = scorer.drain_usage()
    assert drained == (usage, usage, usage)
    assert sum(item.input_tokens for item in drained) == 30
    assert scorer.drain_usage() == ()


def test_provider_error_degrades_to_the_fallback_with_a_note() -> None:
    messages = _messages(4)
    fallback = StubScorer()
    scorer = _scorer(
        RecordingDecisionModel(fail_with=ProviderError("decision model request failed: 500")),
        fallback=fallback,
    )
    scored = scorer.score(task=TASK, messages=messages)
    assert scorer.last_note
    assert "degraded" in scorer.last_note
    assert {item.message.id for item in scored} == {message.id for message in messages}
    assert scored == fallback.score(task=TASK, messages=messages)


async def test_provider_error_degrades_on_the_async_path_too() -> None:
    messages = _messages(2)
    scorer = _scorer(RecordingDecisionModel(fail_with=ProviderError("boom: 429")))
    scored = await scorer.ascore(task=TASK, messages=messages)
    assert scorer.last_note
    assert len(scored) == 2


def test_missing_answer_degrades_to_the_fallback() -> None:
    messages = _messages(3)
    scorer = _scorer(RecordingDecisionModel(drop_answers=True))
    scored = scorer.score(task=TASK, messages=messages)
    assert scorer.last_note
    assert len(scored) == 3


def test_empty_input_short_circuits_without_a_request() -> None:
    model = RecordingDecisionModel()
    scorer = _scorer(model)
    assert scorer.score(task=TASK, messages=[]) == []
    assert model.requests == 0


def test_stub_backed_scorer_is_deterministic_and_reports_usage() -> None:
    messages = _messages(6, text="the compaction test fails with a 400")
    first = _scorer(StubDecisionModel())
    second = _scorer(StubDecisionModel())
    scored_a = first.score(task=TASK, messages=messages)
    scored_b = second.score(task=TASK, messages=messages)
    assert [item.score for item in scored_a] == [item.score for item in scored_b]
    assert all(0.0 <= item.score <= 1.0 for item in scored_a)
    usage = first.drain_usage()
    assert len(usage) == 1
    assert usage[0].input_tokens > 0


def test_configured_thresholds_do_not_change_the_scorer_contract() -> None:
    config = replace(DecisionConfig(), relevance_threshold=0.9, questions_per_request=2)
    messages = _messages(5)
    model = RecordingDecisionModel(probability=0.95)
    scored = _scorer(model, config=config).score(task=TASK, messages=messages)
    assert model.requests == 3
    assert all(item.score == pytest.approx(0.95) for item in scored)
