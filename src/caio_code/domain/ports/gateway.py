"""Model gateway port: one call in, one reply out, usage attached.

The agent loop itself belongs to deepagents; this port covers the calls the
domain makes on its own behalf (compaction, relevance scoring, guardrails, and
the single-shot probes of the evaluation harness). Keeping it narrow is what
makes the stub provider able to replace a real endpoint in every test.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from caio_code.domain.conversation.messages import Message, ToolCall
from caio_code.domain.usage.accounting import TokenUsage


@dataclass(frozen=True, slots=True)
class ToolSchema:
    """One tool the model may call during a completion.

    ``parameters`` is a JSON-schema object; the port stays provider-agnostic and
    the adapter translates it to the wire format. Only callers that run a
    tool-bearing round (the chat-replay probe round) pass schemas; every other
    call site leaves ``tools`` at ``None``.
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelReply:
    """A completion, with the accounting the provider reported."""

    text: str
    usage: TokenUsage
    model: str
    latency_ms: int = 0
    finish_reason: str = "stop"
    tool_calls: tuple[ToolCall, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@runtime_checkable
class ModelGateway(Protocol):
    """Completes a list of messages with a model."""

    model: str

    async def acomplete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        """Async completion. Raises ProviderError on transport or auth failure."""

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        """Synchronous completion."""
