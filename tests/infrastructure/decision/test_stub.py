"""Offline tests for the stub decision model."""

from __future__ import annotations

from caio_code.domain.ports.decision import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionModel,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)
from caio_code.infrastructure.decision.stub import StubDecisionModel

STATE = "the agent must fix the failing test in tests/domain/policy/test_compaction.py"


def test_stub_implements_the_decision_port() -> None:
    model = StubDecisionModel()
    assert isinstance(model, DecisionModel)
    assert model.model == "stub"


def test_noul_probability_is_deterministic_and_inside_the_unit_interval() -> None:
    model = StubDecisionModel()
    questions = {"q": NoulQuestion(instructions="Is this relevant?")}
    first = model.classify(STATE, questions)
    second = model.classify(STATE, questions)
    assert first == second
    answer = first.noul("q")
    assert isinstance(answer, NoulAnswer)
    assert 0.0 <= answer.probability <= 1.0


def test_different_states_may_differ_and_same_state_never_does() -> None:
    model = StubDecisionModel()
    questions = {"q": NoulQuestion(instructions="Is this relevant?")}
    again = model.classify(STATE, questions)
    assert again.noul("q") == model.classify(STATE, questions).noul("q")


def test_choice_answer_is_a_normalized_distribution() -> None:
    model = StubDecisionModel()
    questions = {
        "route": ChoiceQuestion(
            instructions="Which area?",
            criteria={"domain": "pure rules", "infra": "adapters", "cli": "commands"},
        )
    }
    answers = model.classify(STATE, questions)
    answer = answers.choice("route")
    assert isinstance(answer, ChoiceAnswer)
    assert answer.choice in {"domain", "infra", "cli"}
    assert abs(sum(answer.probabilities.values()) - 1.0) < 1e-9
    assert 0.0 <= answer.confidence <= 1.0


def test_score_answer_is_an_expected_level() -> None:
    model = StubDecisionModel()
    questions = {
        "severity": ScoreQuestion(
            instructions="How severe?", criteria=["low", "medium", "high"]
        )
    }
    answers = model.classify(STATE, questions)
    answer = answers.score("severity")
    assert isinstance(answer, ScoreAnswer)
    assert 0.0 <= answer.score <= 2.0
    assert set(answer.probabilities) == {0, 1, 2}
    assert abs(sum(answer.probabilities.values()) - 1.0) < 1e-9


def test_usage_is_a_deterministic_char_proxy() -> None:
    model = StubDecisionModel()
    questions = {"q": NoulQuestion(instructions="Is this relevant?")}
    first = model.classify(STATE, questions)
    second = model.classify(STATE, questions)
    assert first.usage == second.usage
    assert first.usage.input_tokens > 0
    assert first.usage.output_tokens > 0
    assert first.usage.cached_input_tokens == 0


def test_structured_state_is_supported_and_canonical() -> None:
    model = StubDecisionModel()
    questions = {"q": NoulQuestion(instructions="Is this relevant?")}
    state_a = {"task": "x", "messages": [{"id": "1"}, {"id": "2"}]}
    state_b = {"messages": [{"id": "1"}, {"id": "2"}], "task": "x"}
    assert model.classify(state_a, questions) == model.classify(state_b, questions)


async def test_aclassify_matches_classify() -> None:
    model = StubDecisionModel()
    questions = {"q": NoulQuestion(instructions="Is this relevant?")}
    assert await model.aclassify(STATE, questions) == model.classify(STATE, questions)
