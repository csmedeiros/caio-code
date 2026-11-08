"""Deterministic offline decision model.

The stub exists so tests, CI and the ``classify --provider stub`` smoke check
never need the network. It implements the ``DecisionModel`` port exactly and is
deterministic by construction:

- Every probability is derived from a stable hash - the first
  ``HASH_BYTES`` bytes of ``SHA-256(salt + NUL + question_id + NUL + state_text)``
  interpreted as a big-endian integer and divided by ``2**(8*HASH_BYTES)``, which
  lands in [0, 1). ``state_text`` is the state itself when it is a string, and
  its canonical JSON dump (sorted keys) otherwise. SHA-256 is used instead of
  ``hash()`` because Python's builtin hash is salted per process.
- ``Choice`` probabilities are the per-label hashes normalized to sum 1; the
  chosen label is the most probable one, ties broken alphabetically; confidence
  is the chosen label's probability.
- ``Score`` behaves the same over the rubric levels; the score is the expected
  level under the normalized distribution.
- Usage is the char proxy (``ceil(chars / CHARS_PER_TOKEN)``): input counts the
  canonical state text plus every question instruction, output counts the
  canonical JSON of the answers.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping

from caio_code.config import CHARS_PER_TOKEN
from caio_code.domain.errors import ConfigurationError
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
from caio_code.domain.usage.accounting import TokenUsage

STUB_DECISION_MODEL = "stub"
HASH_BYTES = 7
"""Bytes of SHA-256 used per probability: 56 bits, far more resolution than needed."""

_NOUL_SALT = "noul"
_CHOICE_SALT = "choice"
_SCORE_SALT = "score"


def state_text(state: State) -> str:
    """Canonical text of a state, stable across processes and runs."""
    if isinstance(state, str):
        return state
    return json.dumps(state, sort_keys=True, ensure_ascii=False, default=str)


def stable_probability(seed: str, *, salt: str) -> float:
    """A deterministic probability in [0, 1) from SHA-256 of ``salt`` and ``seed``."""
    digest = hashlib.sha256(f"{salt}\x00{seed}".encode()).digest()
    value = int.from_bytes(digest[:HASH_BYTES], "big")
    return value / float(1 << (HASH_BYTES * 8))


def _proxy_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def _normalize(weights: Mapping[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        uniform = 1.0 / len(weights) if weights else 0.0
        return {key: uniform for key in weights}
    return {key: weight / total for key, weight in weights.items()}


class StubDecisionModel:
    """Offline ``DecisionModel``: same state + same questions -> same answers."""

    def __init__(self, *, model: str = STUB_DECISION_MODEL) -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def _answer(self, question_id: str, question: Question, text: str) -> Answer:
        if isinstance(question, NoulQuestion):
            seed = f"{question_id}\x00{text}"
            return NoulAnswer(probability=stable_probability(seed, salt=_NOUL_SALT))
        if isinstance(question, ChoiceQuestion):
            labels = sorted(question.criteria)
            weights = {
                label: stable_probability(f"{question_id}\x00{label}\x00{text}", salt=_CHOICE_SALT)
                for label in labels
            }
            probabilities = _normalize(weights)
            choice = max(labels, key=lambda label: (probabilities[label], label))
            return ChoiceAnswer(
                choice=choice,
                probabilities=probabilities,
                confidence=probabilities[choice],
            )
        if isinstance(question, ScoreQuestion):
            levels = list(range(len(question.criteria)))
            weights = {
                str(level): stable_probability(
                    f"{question_id}\x00{level}\x00{text}", salt=_SCORE_SALT
                )
                for level in levels
            }
            probabilities = _normalize(weights)
            score = sum(level * probabilities[str(level)] for level in levels)
            confidence = max(probabilities.values()) if probabilities else 0.0
            return ScoreAnswer(
                score=score,
                probabilities={level: probabilities[str(level)] for level in levels},
                confidence=confidence,
            )
        msg = f"unknown decision question type: {type(question).__name__}"
        raise ConfigurationError(msg)

    def classify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        text = state_text(state)
        answers: dict[str, Answer] = {
            question_id: self._answer(question_id, question, text)
            for question_id, question in questions.items()
        }
        question_chars = "".join(
            str(getattr(question, "instructions", "")) for question in questions.values()
        )
        answer_chars = json.dumps(
            {name: repr(answer) for name, answer in answers.items()}, sort_keys=True
        )
        usage = TokenUsage(
            input_tokens=_proxy_tokens(text) + _proxy_tokens(question_chars),
            output_tokens=_proxy_tokens(answer_chars),
        )
        return DecisionAnswers(model=self._model, answers=answers, usage=usage, request_id=None)

    async def aclassify(self, state: State, questions: Mapping[str, Question]) -> DecisionAnswers:
        return self.classify(state, questions)


__all__ = ["STUB_DECISION_MODEL", "StubDecisionModel", "stable_probability", "state_text"]
