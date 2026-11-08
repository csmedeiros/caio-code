"""Decision-model factory: settings in, ``DecisionModel`` port implementations out.

Part of the composition root, like ``infrastructure/llm/factory.py``: the only
place allowed to instantiate :class:`SystemClock` for the decision path, and the
only place that decides which credentials a decision run needs. Asking for
``typesafe`` without a key is a :class:`ConfigurationError` naming the variable,
never a crash mid-experiment.
"""

from __future__ import annotations

from caio_code.config import Settings
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.ports.decision import DecisionModel
from caio_code.domain.ports.scorer import RelevanceScorer
from caio_code.domain.ports.time import Clock
from caio_code.infrastructure.decision.scorer import DecisionRelevanceScorer
from caio_code.infrastructure.decision.stub import StubDecisionModel
from caio_code.infrastructure.decision.typesafe import TypeSafeDecisionModel
from caio_code.infrastructure.observability.clocks import SystemClock


def _clock_or_system(clock: Clock | None) -> Clock:
    return clock if clock is not None else SystemClock()


def build_decision_model(settings: Settings, *, clock: Clock | None = None) -> DecisionModel:
    """The decision model named by ``settings.decision.provider``."""
    decision = settings.decision
    if decision.provider == "stub":
        return StubDecisionModel()
    if decision.provider == "typesafe":
        api_key = settings.endpoints.typesafe_api_key.strip()
        if not api_key:
            msg = "decision provider 'typesafe' requires an API key: set TYPESAFE_API_KEY"
            raise ConfigurationError(msg)
        return TypeSafeDecisionModel(
            api_key=api_key,
            model=decision.model,
            base_url=decision.base_url,
            timeout_seconds=decision.timeout_seconds,
            clock=_clock_or_system(clock),
        )
    msg = f"unknown decision provider {decision.provider!r}"
    raise ConfigurationError(msg)


def build_decision_scorer(
    settings: Settings,
    fallback: RelevanceScorer,
    *,
    clock: Clock | None = None,
) -> DecisionRelevanceScorer:
    """The decision-backed relevance scorer, degrading to ``fallback``."""
    model = build_decision_model(settings, clock=clock)
    return DecisionRelevanceScorer(
        model,
        config=settings.decision,
        fallback=fallback,
        clock=_clock_or_system(clock),
    )


__all__ = ["build_decision_model", "build_decision_scorer"]
