"""Offline tests for the TypeSafe decision-model adapter.

The real SDK is driven by an injected ``httpx2`` client with a ``MockTransport``;
no test here touches the network. The fake key must never appear in an error.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest

from caio_code.domain.errors import ConfigurationError, ProviderError
from caio_code.domain.ports.decision import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionModel,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
)
from caio_code.domain.usage.accounting import TokenUsage
from caio_code.infrastructure.decision.typesafe import TypeSafeDecisionModel
from caio_code.infrastructure.observability.clocks import FixedClock

START = datetime(2026, 1, 1, tzinfo=UTC)
FAKE_KEY = "ts-FAKE-KEY-do-not-print"
REQUEST_ID = "req-123"


def _response_body(answers: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "model": "jev-latest",
        "answers": answers or {"q": {"type": "noul", "noul": 0.87}},
        "usage": {"input_tokens": 41, "output_tokens": 7},
    }


def _model(
    handler: Any,
    *,
    api_key: str = FAKE_KEY,
    model: str = "jev-latest",
) -> TypeSafeDecisionModel:
    transport = httpx2.MockTransport(handler)
    return TypeSafeDecisionModel(
        api_key=api_key,
        model=model,
        base_url="https://api.invalid",
        timeout_seconds=5.0,
        clock=FixedClock(START),
        client=httpx2.Client(transport=transport),
        async_client=httpx2.AsyncClient(transport=transport),
    )


def _ok_handler(body: dict[str, Any]) -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json=body, headers={"x-typesafe-request-id": REQUEST_ID}
        )

    return handler


def _status_handler(status: int) -> Any:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": "denied"})

    return handler


def test_empty_api_key_raises_configuration_error_naming_the_env_var() -> None:
    with pytest.raises(ConfigurationError, match="TYPESAFE_API_KEY"):
        TypeSafeDecisionModel(
            api_key="  ",
            model="jev-latest",
            base_url="https://api.invalid",
            timeout_seconds=5.0,
            clock=FixedClock(START),
        )


def test_adapter_implements_the_decision_port() -> None:
    model = _model(_ok_handler(_response_body()))
    assert isinstance(model, DecisionModel)
    assert model.model == "jev-latest"


def test_all_three_question_types_are_mapped_onto_the_wire() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=_response_body(), headers={})

    model = _model(handler)
    model.classify(
        "some state",
        {
            "n": NoulQuestion(
                instructions="needed later?", true_criteria="yes because", false_criteria="no because"
            ),
            "c": ChoiceQuestion(instructions="which?", criteria={"a": "first", "b": "second"}),
            "s": ScoreQuestion(instructions="how bad?", criteria=["calm", "angry"]),
        },
    )
    assert len(seen) == 1
    payload = seen[0]
    assert payload["model"] == "jev-latest"
    assert payload["state"] == "some state"
    questions = payload["questions"]
    assert questions["n"]["type"] == "noul"
    assert questions["n"]["criteria"] == {"true": "yes because", "false": "no because"}
    assert questions["c"]["type"] == "choice"
    assert questions["c"]["criteria"] == {"a": "first", "b": "second"}
    assert questions["s"]["type"] == "score"
    assert questions["s"]["criteria"] == ["calm", "angry"]


def test_noul_without_criteria_sends_no_criteria() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=_response_body(), headers={})

    _model(handler).classify("s", {"n": NoulQuestion(instructions="needed later?")})
    assert "criteria" not in seen[0]["questions"]["n"]


def test_all_three_answer_types_and_usage_are_mapped_back() -> None:
    body = _response_body(
        {
            "n": {"type": "noul", "noul": 0.87},
            "c": {
                "type": "choice",
                "choice": "a",
                "probabilities": {"a": 0.7, "b": 0.3},
                "confidence": 0.6,
            },
            "s": {
                "type": "score",
                "score": 1.35,
                "legend": {0: "calm", 1: "angry"},
                "probabilities": {0: 0.4, 1: 0.6},
                "confidence": 0.55,
            },
        }
    )
    answers = _model(_ok_handler(body)).classify("s", {})
    assert isinstance(answers.noul("n"), NoulAnswer)
    assert answers.noul("n") == NoulAnswer(probability=0.87)
    choice = answers.choice("c")
    assert isinstance(choice, ChoiceAnswer)
    assert choice == ChoiceAnswer(choice="a", probabilities={"a": 0.7, "b": 0.3}, confidence=0.6)
    score = answers.score("s")
    assert isinstance(score, ScoreAnswer)
    assert score == ScoreAnswer(score=1.35, probabilities={0: 0.4, 1: 0.6}, confidence=0.55)
    assert answers.usage == TokenUsage(input_tokens=41, output_tokens=7)
    assert answers.model == "jev-latest"
    assert answers.request_id == REQUEST_ID


def test_missing_usage_fields_map_to_zero_tokens() -> None:
    body = {"model": "jev-latest", "answers": {"n": {"type": "noul", "noul": 0.1}}, "usage": {}}
    answers = _model(_ok_handler(body)).classify("s", {})
    assert answers.usage == TokenUsage()


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_failures_become_provider_errors_with_status_but_no_key(status: int) -> None:
    model = _model(_status_handler(status))
    with pytest.raises(ProviderError) as excinfo:
        model.classify("secret state text", {"n": NoulQuestion(instructions="q?")})
    message = str(excinfo.value)
    assert str(status) in message
    assert FAKE_KEY not in message
    assert "secret state text" not in message


async def test_async_path_maps_answers_and_errors() -> None:
    model = _model(_ok_handler(_response_body()))
    answers = await model.aclassify("s", {"q": NoulQuestion(instructions="q?")})
    assert answers.noul("q") == NoulAnswer(probability=0.87)

    failing = _model(_status_handler(401))
    with pytest.raises(ProviderError, match="401"):
        await failing.aclassify("s", {"q": NoulQuestion(instructions="q?")})


def test_latency_is_measured_with_the_injected_clock() -> None:
    model = _model(_ok_handler(_response_body()))
    model.classify("s", {})
    assert model.last_latency_ms > 0
