"""The single token-counting port.

Only implementations of this protocol count tokens. No module divides
``len(text)`` by four on its own: if the formula changes, the experiment's
numbers must change everywhere at once.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from caio_code.domain.conversation.messages import Message, Transcript


@runtime_checkable
class TokenCounter(Protocol):
    """Counts tokens deterministically for text, messages and transcripts."""

    name: str

    def count_text(self, text: str) -> int:
        """Cost of one string."""

    def count_message(self, message: Message) -> int:
        """Cost of one message, including its tool calls."""

    def count_messages(self, messages: Iterable[Message]) -> int:
        """Cost of a sequence of messages, summed message by message."""

    def count_transcript(self, transcript: Transcript) -> int:
        """Cost of a whole transcript."""


def count_sequence(counter: TokenCounter, messages: Sequence[Message]) -> list[int]:
    """Per-message costs, in order. Useful to build cumulative budgets."""
    return [counter.count_message(message) for message in messages]
