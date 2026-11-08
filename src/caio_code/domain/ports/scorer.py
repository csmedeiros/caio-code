"""Relevance scoring port, used by the message-selection policy.

The policy itself stays pure: it receives scores and decides what fits. Producing
the scores is an infrastructure concern, either lexical (deterministic, offline)
or a model call (the auxiliary endpoint).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from caio_code.domain.conversation.messages import Message


@dataclass(frozen=True, slots=True)
class ScoredMessage:
    """A message, its index in the transcript, and its relevance score."""

    index: int
    score: float
    message: Message


@runtime_checkable
class RelevanceScorer(Protocol):
    """Scores how relevant each message is to the current task."""

    name: str

    async def ascore(
        self,
        *,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        """Score every message once, returning one entry per input message."""

    def score(
        self,
        *,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        """Synchronous variant."""
