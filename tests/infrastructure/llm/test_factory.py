"""Offline tests for the provider factory."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from caio_code.config import (
    DecisionConfig,
    EndpointConfig,
    ProviderConfig,
    SelectionConfig,
    Settings,
)
from caio_code.domain.errors import ConfigurationError
from caio_code.infrastructure.decision.scorer import DecisionRelevanceScorer
from caio_code.infrastructure.llm.factory import (
    build_gateway,
    build_scorer,
    build_summarizer,
)
from caio_code.infrastructure.llm.openai_compatible import (
    ModelRelevanceScorer,
    OpenAICompatibleGateway,
    OpenAICompatibleSummarizer,
)
from caio_code.infrastructure.llm.stub import StubGateway, StubScorer, StubSummarizer
from caio_code.infrastructure.observability.clocks import FixedClock, SystemClock

START = datetime(2026, 1, 1, tzinfo=UTC)


def _clock() -> FixedClock:
    return FixedClock(START)


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


class TestBuildGateway:
    def test_default_is_stub_with_the_configured_model(self) -> None:
        gateway = build_gateway(_settings(), clock=_clock())
        assert isinstance(gateway, StubGateway)
        assert gateway.model == "qwen3.8-max"

    def test_auxiliary_uses_aux_provider_and_model(self) -> None:
        gateway = build_gateway(_settings(), auxiliary=True, clock=_clock())
        assert isinstance(gateway, StubGateway)
        assert gateway.model == "qwen3.8-flash"

    def test_system_clock_is_used_when_none_injected(self) -> None:
        gateway = build_gateway(_settings())
        assert isinstance(gateway, StubGateway)
        reply = gateway.complete([])
        assert reply.latency_ms >= 0

    def test_openai_compatible_without_credentials_raises(self) -> None:
        settings = _settings(
            provider=ProviderConfig(provider="openai_compatible"),
            endpoints=EndpointConfig(),
        )
        with pytest.raises(ConfigurationError, match="OPENAI_BASE_URL"):
            build_gateway(settings, clock=_clock())

    def test_openai_compatible_with_credentials_builds(self) -> None:
        settings = _settings(
            provider=ProviderConfig(provider="openai_compatible"),
            endpoints=EndpointConfig(
                openai_base_url="http://localhost:1/v1", openai_api_key="k"
            ),
        )
        gateway = build_gateway(settings, clock=_clock())
        assert isinstance(gateway, OpenAICompatibleGateway)
        assert gateway.model == "qwen3.8-max"

    def test_typesafe_chat_provider_is_refused_with_an_explanation(self) -> None:
        settings = _settings(
            provider=ProviderConfig(provider="typesafe"),  # type: ignore[arg-type]
            endpoints=EndpointConfig(typesafe_api_key="k"),
        )
        with pytest.raises(ConfigurationError, match="decision model"):
            build_gateway(settings, clock=_clock())
        with pytest.raises(ConfigurationError, match="CAIO_CODE_DECISION_PROVIDER"):
            build_gateway(settings, clock=_clock())


class TestBuildSummarizer:
    def test_stub_by_default(self) -> None:
        summarizer = build_summarizer(_settings(), clock=_clock())
        assert isinstance(summarizer, StubSummarizer)
        result = summarizer.summarize("[User]: do x", max_tokens=1_024)
        assert result.is_usable

    def test_dedicated_summarizer_model_is_honoured(self) -> None:
        settings = _settings()
        settings = dataclasses.replace(
            settings,
            compaction=dataclasses.replace(settings.compaction, summarizer_model="custom-sum"),
        )
        summarizer = build_summarizer(settings, clock=_clock())
        assert isinstance(summarizer, StubSummarizer)
        assert summarizer.summarize("p", max_tokens=16).model == "custom-sum"

    def test_openai_compatible_aux_without_credentials_raises(self) -> None:
        settings = _settings(provider=ProviderConfig(aux_provider="openai_compatible"))
        with pytest.raises(ConfigurationError):
            build_summarizer(settings, clock=_clock())

    def test_openai_compatible_aux_builds(self) -> None:
        settings = _settings(
            provider=ProviderConfig(aux_provider="openai_compatible"),
            endpoints=EndpointConfig(
                openai_base_url="http://localhost:1/v1", openai_api_key="k"
            ),
        )
        summarizer = build_summarizer(settings, clock=_clock())
        assert isinstance(summarizer, OpenAICompatibleSummarizer)

    def test_typesafe_aux_summarizer_is_refused_with_an_explanation(self) -> None:
        settings = _settings(
            provider=ProviderConfig(aux_provider="typesafe"),  # type: ignore[arg-type]
            endpoints=EndpointConfig(typesafe_api_key="k"),
        )
        with pytest.raises(ConfigurationError, match=r"infrastructure\.decision"):
            build_summarizer(settings, clock=_clock())


class TestBuildScorer:
    def test_lexical_configuration_returns_the_fallback(self) -> None:
        fallback = StubScorer()
        scorer = build_scorer(_settings(), fallback, clock=_clock())
        assert scorer is fallback

    def test_model_configuration_wraps_the_aux_gateway(self) -> None:
        settings = _settings(selection=SelectionConfig(scorer="model"))
        scorer = build_scorer(settings, StubScorer(), clock=_clock())
        assert isinstance(scorer, ModelRelevanceScorer)

    def test_model_configuration_requires_aux_credentials(self) -> None:
        settings = _settings(
            selection=SelectionConfig(scorer="model"),
            provider=ProviderConfig(aux_provider="openai_compatible"),
            endpoints=EndpointConfig(),
        )
        with pytest.raises(ConfigurationError):
            build_scorer(settings, StubScorer(), clock=_clock())

    def test_decision_configuration_builds_the_decision_scorer(self) -> None:
        settings = _settings(
            selection=SelectionConfig(scorer="decision"),
            decision=DecisionConfig(provider="stub"),
        )
        scorer = build_scorer(settings, StubScorer(), clock=_clock())
        assert isinstance(scorer, DecisionRelevanceScorer)
        assert scorer.name == "decision/stub"


def test_system_clock_is_available_to_the_factory() -> None:
    assert isinstance(SystemClock().now(), datetime)
