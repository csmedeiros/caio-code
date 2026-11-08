"""Token counters.

Two implementations of the same port:

``CharProxyTokenCounter``
    The thesis proxy ``C = sum_m ceil(|m| / chars_per_token)``, summed per
    message. Deterministic, offline, and the counter every unit test and every
    CI run uses. It is also the estimator the reference harnesses use for their
    own context pressure, which keeps the comparison honest.

``TiktokenCounter``
    Real BPE counts, for reporting next to the provider's own numbers. It
    downloads an encoding on first use, so it is never the default and never
    runs in CI.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from functools import lru_cache

from caio_code.config import CHARS_PER_TOKEN
from caio_code.domain.conversation.messages import Message, Transcript
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.ports.tokenizer import TokenCounter


class CharProxyTokenCounter(TokenCounter):
    """``ceil(chars / chars_per_token)`` per message, summed."""

    def __init__(self, *, chars_per_token: int = CHARS_PER_TOKEN) -> None:
        if chars_per_token <= 0:
            msg = f"chars_per_token must be positive, got {chars_per_token}"
            raise ConfigurationError(msg)
        self._chars_per_token = chars_per_token

    @property
    def name(self) -> str:
        return f"char_proxy/{self._chars_per_token}"

    @property
    def chars_per_token(self) -> int:
        return self._chars_per_token

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        return math.ceil(len(text) / self._chars_per_token)

    def count_message(self, message: Message) -> int:
        return self.count_text(message.text) + sum(
            self.count_text(call.name + call.arguments) for call in message.tool_calls
        )

    def count_messages(self, messages: Iterable[Message]) -> int:
        return sum(self.count_message(message) for message in messages)

    def count_transcript(self, transcript: Transcript) -> int:
        return self.count_messages(transcript.messages)


class TiktokenCounter(TokenCounter):
    """BPE counts from tiktoken. Import and encoding load are lazy."""

    def __init__(self, *, encoding_name: str = "o200k_base") -> None:
        self._encoding_name = encoding_name
        self._encoder = None

    @property
    def name(self) -> str:
        return f"tiktoken/{self._encoding_name}"

    def _load(self):
        if self._encoder is None:
            try:
                import tiktoken
            except ImportError as exc:  # pragma: no cover - optional extra
                msg = "install the 'tokens' extra to use TiktokenCounter"
                raise ConfigurationError(msg) from exc
            try:
                self._encoder = tiktoken.get_encoding(self._encoding_name)
            except Exception as exc:
                msg = f"tiktoken encoding {self._encoding_name!r} unavailable: {exc}"
                raise ConfigurationError(msg) from exc
        return self._encoder

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        return len(self._load().encode(text, disallowed_special=()))

    def count_message(self, message: Message) -> int:
        total = self.count_text(message.text)
        for call in message.tool_calls:
            total += self.count_text(call.name) + self.count_text(call.arguments)
        return total

    def count_messages(self, messages: Iterable[Message]) -> int:
        return sum(self.count_message(message) for message in messages)

    def count_transcript(self, transcript: Transcript) -> int:
        return self.count_messages(transcript.messages)


@lru_cache(maxsize=8)
def build_counter(kind: str, *, chars_per_token: int = CHARS_PER_TOKEN, encoding: str = "o200k_base") -> TokenCounter:
    """Factory used by the composition root."""
    if kind == "char_proxy":
        return CharProxyTokenCounter(chars_per_token=chars_per_token)
    if kind == "tiktoken":
        return TiktokenCounter(encoding_name=encoding)
    msg = f"unknown token counter {kind!r}; expected 'char_proxy' or 'tiktoken'"
    raise ConfigurationError(msg)
