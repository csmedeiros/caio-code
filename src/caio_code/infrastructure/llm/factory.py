"""Provider factory: settings in, port implementations out.

This module is part of the composition root, and the only place outside
``observability.clocks`` allowed to instantiate :class:`SystemClock`. It is
also the only place that decides which credentials a run needs: asking for a
real provider without the matching environment variables is a
:class:`ConfigurationError` naming the variable, not a crash mid-experiment.
"""

from __future__ import annotations

from caio_code.config import ProviderConfig, Settings
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.ports.gateway import ModelGateway
from caio_code.domain.ports.scorer import RelevanceScorer
from caio_code.domain.ports.summarizer import Summarizer
from caio_code.domain.ports.time import Clock
from caio_code.infrastructure.llm.openai_compatible import (
    ModelRelevanceScorer,
    OpenAICompatibleGateway,
    OpenAICompatibleSummarizer,
)
from caio_code.infrastructure.llm.stub import StubGateway, StubSummarizer
from caio_code.infrastructure.observability.clocks import SystemClock

TYPESAFE_NOT_A_CHAT_PROVIDER = (
    "'typesafe' is not a chat provider: Jev is a decision model that answers typed questions "
    "with probabilities (ADR 0005). Configure it through CAIO_CODE_DECISION_PROVIDER and "
    "caio_code.infrastructure.decision, not through the chat provider settings"
)


def _clock_or_system(clock: Clock | None) -> Clock:
    return clock if clock is not None else SystemClock()


def _typesafe_is_not_a_chat_provider() -> ConfigurationError:
    return ConfigurationError(TYPESAFE_NOT_A_CHAT_PROVIDER)


def build_gateway(
    settings: Settings,
    *,
    auxiliary: bool = False,
    clock: Clock | None = None,
) -> ModelGateway:
    """The gateway for the agent loop (``auxiliary=False``) or for aux calls."""
    provider = settings.provider
    kind = provider.aux_provider if auxiliary else provider.provider
    model = provider.aux_model if auxiliary else provider.model
    resolved_clock = _clock_or_system(clock)
    endpoints = settings.endpoints

    if kind == "stub":
        return StubGateway(clock=resolved_clock, model=model)
    if kind == "openai_compatible":
        if not endpoints.openai_base_url.strip() or not endpoints.openai_api_key.strip():
            msg = (
                "provider 'openai_compatible' requires credentials: "
                "set OPENAI_BASE_URL and OPENAI_API_KEY"
            )
            raise ConfigurationError(msg)
        return OpenAICompatibleGateway(
            base_url=endpoints.openai_base_url,
            api_key=endpoints.openai_api_key,
            model=model,
            clock=resolved_clock,
            temperature=provider.temperature,
            max_output_tokens=provider.max_output_tokens,
            timeout_seconds=_timeout_for(provider, auxiliary=auxiliary),
            max_retries=provider.max_retries,
        )
    if kind == "typesafe":
        raise _typesafe_is_not_a_chat_provider()
    msg = f"unknown provider {kind!r}"
    raise ConfigurationError(msg)


def _timeout_for(provider: ProviderConfig, *, auxiliary: bool) -> float:
    """Auxiliary calls summarize tens of thousands of tokens and need more room."""
    return provider.aux_timeout_seconds if auxiliary else provider.timeout_seconds


def build_summarizer(settings: Settings, *, clock: Clock | None = None) -> Summarizer:
    """The summarizer for compaction, over the auxiliary provider."""
    kind = settings.provider.aux_provider
    resolved_clock = _clock_or_system(clock)
    model = settings.compaction.summarizer_model or settings.provider.aux_model

    if kind == "stub":
        return StubSummarizer(model=model, clock=resolved_clock)
    if kind == "typesafe":
        raise _typesafe_is_not_a_chat_provider()
    gateway = build_gateway(settings, auxiliary=True, clock=resolved_clock)
    return OpenAICompatibleSummarizer(gateway=gateway)


def build_scorer(
    settings: Settings,
    fallback: RelevanceScorer,
    *,
    clock: Clock | None = None,
) -> RelevanceScorer:
    """The relevance scorer: model- or decision-backed when configured, else the fallback."""
    if settings.selection.scorer == "decision":
        # Lazy: the decision package pulls the langchain_typesafe SDK, which the
        # chat path must not require (ADR 0005).
        from caio_code.infrastructure.decision.factory import build_decision_scorer

        return build_decision_scorer(settings, fallback, clock=_clock_or_system(clock))
    if settings.selection.scorer != "model":
        return fallback
    gateway = build_gateway(settings, auxiliary=True, clock=_clock_or_system(clock))
    return ModelRelevanceScorer(gateway=gateway, fallback=fallback)
