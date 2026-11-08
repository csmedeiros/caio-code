"""TypeSafe Jev adapter for the decision-model port.

Jev is not a chat model: it answers typed questions (``Noul``/``Choice``/
``Score``) about a state with probabilities. This module translates between the
domain vocabulary (:mod:`caio_code.domain.ports.decision`) and the
``langchain_typesafe`` SDK, and nothing else.

Invariants:

- The constructor receives the resolved settings pieces explicitly
  (``api_key``, ``model``, ``base_url``, ``timeout_seconds``, ``clock``); this
  module never reads the environment.
- A missing API key is a :class:`ConfigurationError` naming ``TYPESAFE_API_KEY``.
- Every SDK or transport failure becomes a :class:`ProviderError` whose message
  keeps the HTTP status and the TypeSafe request id - the SDK already excludes
  body and headers from ``str()`` - and never the API key or the classified
  state.
- Latency is measured with the injected :class:`Clock`, never ``time.time()``.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any

import httpx2
from langchain_core._api import LangChainBetaWarning
from langchain_typesafe import (
    Choice,
    Noul,
    NoulCriteria,
    Score,
    TypeSafeClassifier,
)
from langchain_typesafe.client import TypeSafeAPIError, TypeSafeError
from langchain_typesafe.types import (
    ChoiceAnswer as SdkChoiceAnswer,
)
from langchain_typesafe.types import (
    ClassifierResponse,
)
from langchain_typesafe.types import (
    NoulAnswer as SdkNoulAnswer,
)
from langchain_typesafe.types import (
    Question as SdkQuestion,
)
from langchain_typesafe.types import (
    ScoreAnswer as SdkScoreAnswer,
)

from caio_code.domain.errors import ConfigurationError, ProviderError
from caio_code.domain.ports.decision import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionAnswers,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    State,
)
from caio_code.domain.ports.time import Clock
from caio_code.domain.usage.accounting import TokenUsage


def to_sdk_question(question: Question) -> SdkQuestion:
    """Map a domain question onto its SDK counterpart."""
    match question:
        case NoulQuestion(
            instructions=instructions,
            true_criteria=true_criteria,
            false_criteria=false_criteria,
        ):
            criteria = (
                NoulCriteria(true=true_criteria, false=false_criteria)
                if true_criteria is not None or false_criteria is not None
                else None
            )
            return Noul(instructions=instructions, criteria=criteria)
        case ChoiceQuestion(instructions=instructions, criteria=criteria):
            return Choice(instructions=instructions, criteria=dict(criteria))
        case ScoreQuestion(instructions=instructions, criteria=criteria):
            return Score(instructions=instructions, criteria=list(criteria))
        case _:  # pragma: no cover - the union above is exhaustive
            msg = f"unknown decision question type: {type(question).__name__}"
            raise ConfigurationError(msg)


def to_domain_answer(answer: Any) -> Answer:
    """Map one SDK answer onto its domain counterpart."""
    if isinstance(answer, SdkNoulAnswer):
        return NoulAnswer(probability=answer.noul)
    if isinstance(answer, SdkChoiceAnswer):
        return ChoiceAnswer(
            choice=answer.choice,
            probabilities=dict(answer.probabilities),
            confidence=answer.confidence,
        )
    if isinstance(answer, SdkScoreAnswer):
        return ScoreAnswer(
            score=answer.score,
            probabilities={int(level): probability for level, probability in answer.probabilities.items()},
            confidence=answer.confidence,
        )
    msg = f"decision model returned an unknown answer type: {type(answer).__name__}"
    raise ProviderError(msg)


def usage_from_response(response: ClassifierResponse) -> TokenUsage:
    """Map the SDK usage onto the domain ``TokenUsage``; fields may be absent."""
    return TokenUsage(
        input_tokens=max(0, response.usage.input_tokens or 0),
        output_tokens=max(0, response.usage.output_tokens or 0),
    )


def answers_from_response(response: ClassifierResponse) -> DecisionAnswers:
    """Map a whole SDK response onto the domain ``DecisionAnswers``."""
    return DecisionAnswers(
        model=response.model,
        answers={name: to_domain_answer(answer) for name, answer in response.answers.items()},
        usage=usage_from_response(response),
        request_id=response.request_id,
    )


class TypeSafeDecisionModel:
    """``DecisionModel`` over ``TypeSafeClassifier`` (Jev)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        clock: Clock,
        client: httpx2.Client | None = None,
        async_client: httpx2.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            msg = "the typesafe decision provider requires an API key: set TYPESAFE_API_KEY"
            raise ConfigurationError(msg)
        if not base_url.strip():
            msg = "the typesafe decision provider requires a base URL (TYPESAFE_BASE_URL)"
            raise ConfigurationError(msg)
        self._clock = clock
        self._model = model
        # The SDK marks TypeSafeClassifier as beta and warns on direct
        # instantiation; this adapter is the deliberate, single point of use,
        # and the repository treats warnings as errors.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LangChainBetaWarning)
            self._classifier = TypeSafeClassifier(
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout_seconds,
                client=client,
                async_client=async_client,
            )
        self._last_latency_ms = 0

    @property
    def model(self) -> str:
        return self._model

    @property
    def last_latency_ms(self) -> int:
        """Latency of the most recent classification, measured with the Clock."""
        return self._last_latency_ms

    def _request(self, state: State, questions: Mapping[str, Question]) -> dict[str, Any]:
        return {
            "state": state,
            "questions": {name: to_sdk_question(question) for name, question in questions.items()},
        }

    def _failure(self, exc: TypeSafeError) -> ProviderError:
        """SDK errors are sanitized by design: str() carries status and request id only."""
        detail = f"status {exc.status}" if isinstance(exc, TypeSafeAPIError) else str(exc)
        request_id = exc.request_id if isinstance(exc, TypeSafeAPIError) else None
        if request_id is not None:
            detail = f"{detail}, request_id={request_id}"
        msg = f"decision model {self._model!r} request failed: {detail}"
        return ProviderError(msg)

    def classify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        started_at = self._clock.monotonic_ms()
        try:
            response = self._classifier.invoke(self._request(state, questions))
        except TypeSafeError as exc:
            raise self._failure(exc) from exc
        except (TypeError, ValueError) as exc:
            raise self._unserializable(exc) from exc
        self._last_latency_ms = self._clock.monotonic_ms() - started_at
        return answers_from_response(response)

    async def aclassify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        started_at = self._clock.monotonic_ms()
        try:
            response = await self._classifier.ainvoke(self._request(state, questions))
        except TypeSafeError as exc:
            raise self._failure(exc) from exc
        except (TypeError, ValueError) as exc:
            raise self._unserializable(exc) from exc
        self._last_latency_ms = self._clock.monotonic_ms() - started_at
        return answers_from_response(response)

    def _unserializable(self, exc: TypeError | ValueError) -> ProviderError:
        # The state is never interpolated: a classification failure must not leak
        # the classified content through the error message.
        msg = f"decision model {self._model!r} could not serialize the request: {type(exc).__name__}"
        return ProviderError(msg)


__all__ = [
    "TypeSafeDecisionModel",
    "answers_from_response",
    "to_domain_answer",
    "to_sdk_question",
    "usage_from_response",
]
