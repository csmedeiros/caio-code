"""Offline tests for the decision-based tool-risk advisor."""

from __future__ import annotations

from collections.abc import Mapping

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
from caio_code.domain.usage.accounting import TokenUsage
from caio_code.infrastructure.decision.risk import (
    RISK_QUESTION_ID,
    DecisionRiskAdvisor,
    RiskAssessment,
)

USAGE = TokenUsage(input_tokens=12, output_tokens=3)


class ScriptedRiskModel:
    """Answers the risk Noul with a scripted probability."""

    def __init__(self, *, probability: float | None = None, missing: bool = False) -> None:
        self.model = "scripted-jev"
        self.states: list[State] = []
        self._probability = probability
        self._missing = missing

    def classify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        self.states.append(state)
        answers: dict[str, NoulAnswer] = (
            {}
            if self._missing
            else {RISK_QUESTION_ID: NoulAnswer(probability=self._probability or 0.0)}
        )
        return DecisionAnswers(model=self.model, answers=answers, usage=USAGE)

    async def aclassify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        return self.classify(state, questions)


def _messages(count: int) -> list[Message]:
    return [
        Message(id=f"m{index}", role=Role.USER, text=f"please run the tests {index}")
        for index in range(count)
    ]


def _advisor(model: DecisionModel, *, threshold: float = 0.5) -> DecisionRiskAdvisor:
    return DecisionRiskAdvisor(model, config=DecisionConfig(risk_threshold=threshold))


async def test_probability_at_or_above_the_threshold_is_risky() -> None:
    advisor = _advisor(ScriptedRiskModel(probability=0.9))
    assessment = await advisor.assess(
        tool_name="shell", arguments='{"cmd": "rm -rf /"}', recent_messages=_messages(2)
    )
    assert isinstance(assessment, RiskAssessment)
    assert assessment.risky is True
    assert assessment.probability == pytest.approx(0.9)
    assert "0.900" in assessment.reason


async def test_probability_below_the_threshold_is_not_risky() -> None:
    advisor = _advisor(ScriptedRiskModel(probability=0.1))
    assessment = await advisor.assess(
        tool_name="read_file", arguments='{"path": "README.md"}', recent_messages=_messages(2)
    )
    assert assessment.risky is False
    assert assessment.probability == pytest.approx(0.1)


async def test_threshold_comes_from_the_config() -> None:
    advisor = _advisor(ScriptedRiskModel(probability=0.7), threshold=0.8)
    assessment = await advisor.assess(
        tool_name="shell", arguments="{}", recent_messages=_messages(1)
    )
    assert assessment.risky is False


async def test_state_carries_the_tool_call_and_a_capped_message_window() -> None:
    model = ScriptedRiskModel(probability=0.2)
    advisor = _advisor(model)
    await advisor.assess(
        tool_name="write_file",
        arguments='{"path": "a.py"}',
        recent_messages=_messages(40),
    )
    state = model.states[0]
    assert isinstance(state, dict)
    assert state["tool_call"] == {"name": "write_file", "arguments": '{"path": "a.py"}'}
    messages = state["messages"]
    assert isinstance(messages, list)
    assert len(messages) == 30  # MAX_RECENT_MESSAGES, Auto Mode's window


async def test_usage_is_recorded_and_drained() -> None:
    advisor = _advisor(ScriptedRiskModel(probability=0.2))
    await advisor.assess(tool_name="shell", arguments="{}", recent_messages=[])
    await advisor.assess(tool_name="shell", arguments="{}", recent_messages=[])
    drained = advisor.drain_usage()
    assert drained == (USAGE, USAGE)
    assert advisor.drain_usage() == ()


async def test_missing_answer_is_a_provider_error() -> None:
    advisor = _advisor(ScriptedRiskModel(missing=True))
    with pytest.raises(ProviderError):
        await advisor.assess(tool_name="shell", arguments="{}", recent_messages=[])
