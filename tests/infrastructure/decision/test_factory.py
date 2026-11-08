"""Offline tests for the decision-model factory."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from caio_code.config import DecisionConfig, EndpointConfig, Settings
from caio_code.domain.errors import ConfigurationError
from caio_code.infrastructure.decision.factory import (
    build_decision_model,
    build_decision_scorer,
)
from caio_code.infrastructure.decision.scorer import DecisionRelevanceScorer
from caio_code.infrastructure.decision.stub import StubDecisionModel
from caio_code.infrastructure.decision.typesafe import TypeSafeDecisionModel
from caio_code.infrastructure.llm.stub import StubScorer
from caio_code.infrastructure.observability.clocks import FixedClock

START = datetime(2026, 1, 1, tzinfo=UTC)


def _clock() -> FixedClock:
    return FixedClock(START)


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def test_default_provider_is_the_offline_stub() -> None:
    model = build_decision_model(_settings(), clock=_clock())
    assert isinstance(model, StubDecisionModel)
    assert model.model == "stub"


def test_typesafe_without_a_key_raises_naming_the_env_var() -> None:
    settings = _settings(
        decision=DecisionConfig(provider="typesafe"),
        endpoints=EndpointConfig(),
    )
    with pytest.raises(ConfigurationError, match="TYPESAFE_API_KEY"):
        build_decision_model(settings, clock=_clock())


def test_typesafe_with_a_key_builds_the_adapter() -> None:
    settings = _settings(
        decision=DecisionConfig(provider="typesafe", model="jev-2026-01"),
        endpoints=EndpointConfig(typesafe_api_key="k"),
    )
    model = build_decision_model(settings, clock=_clock())
    assert isinstance(model, TypeSafeDecisionModel)
    assert model.model == "jev-2026-01"


def test_system_clock_is_used_when_none_injected() -> None:
    model = build_decision_model(_settings())
    assert isinstance(model, StubDecisionModel)


def test_scorer_is_built_over_the_configured_model_and_fallback() -> None:
    settings = _settings(
        decision=DecisionConfig(provider="typesafe", questions_per_request=7),
        endpoints=EndpointConfig(typesafe_api_key="k"),
    )
    fallback = StubScorer()
    scorer = build_decision_scorer(settings, fallback, clock=_clock())
    assert isinstance(scorer, DecisionRelevanceScorer)
    assert scorer.name == "decision/jev-latest"
