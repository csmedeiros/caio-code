"""Conversation model: the provider-agnostic transcript the policies operate on.

The domain never imports LangChain. Infrastructure maps LangChain messages to
:class:`Message` and back, and applies a :class:`~caio_code.domain.policy.base.PolicyDecision`
by index, so the objects handed to the model stay the provider's own.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.errors import ContextBudgetError


class Role(StrEnum):
    """Who produced a message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool invocation requested by the assistant."""

    id: str
    name: str
    arguments: str

    def char_count(self) -> int:
        return len(self.name) + len(self.arguments)


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of the transcript.

    ``pinned`` marks messages a policy may never drop: the task statement and
    anything the user asked to keep. ``tokens`` is a cache filled by the token
    counter; it stays ``None`` until something counts it.
    """

    id: str
    role: Role
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None
    pinned: bool = False
    tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def char_count(self) -> int:
        """Characters this message contributes to the proxy token count."""
        return len(self.text) + sum(call.char_count() for call in self.tool_calls)

    def is_tool_result(self) -> bool:
        return self.role is Role.TOOL

    def with_text(self, text: str, *, marker: str | None = None) -> Message:
        """A copy with new text, optionally tagged so the edit is auditable."""
        metadata = dict(self.metadata)
        if marker is not None:
            edits = list(metadata.get("edits", ()))
            edits.append(marker)
            metadata["edits"] = tuple(edits)
        return Message(
            id=self.id,
            role=self.role,
            text=text,
            tool_calls=self.tool_calls,
            tool_call_id=self.tool_call_id,
            name=self.name,
            pinned=self.pinned,
            tokens=None,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class Transcript:
    """An ordered, immutable list of messages."""

    messages: tuple[Message, ...] = ()

    def __len__(self) -> int:
        return len(self.messages)

    def __iter__(self) -> Iterator[Message]:
        return iter(self.messages)

    def __getitem__(self, index: int) -> Message:
        return self.messages[index]

    @classmethod
    def of(cls, messages: Iterable[Message]) -> Transcript:
        return cls(tuple(messages))

    def append(self, message: Message) -> Transcript:
        return Transcript((*self.messages, message))

    def extend(self, messages: Iterable[Message]) -> Transcript:
        return Transcript((*self.messages, *messages))

    def take(self, indices: Sequence[int]) -> Transcript:
        """Messages at ``indices``, in chronological order regardless of input order."""
        ordered = sorted(set(indices))
        return Transcript(tuple(self.messages[i] for i in ordered if 0 <= i < len(self.messages)))

    def total_chars(self) -> int:
        return sum(message.char_count() for message in self.messages)

    def indices_of_role(self, role: Role) -> tuple[int, ...]:
        return tuple(i for i, message in enumerate(self.messages) if message.role is role)

    def pinned_indices(self) -> tuple[int, ...]:
        return tuple(i for i, message in enumerate(self.messages) if message.pinned)

    def tail(self, count: int) -> Transcript:
        if count <= 0:
            return Transcript()
        return Transcript(self.messages[-count:])


def require_fits_budget(tokens: int, budget: TokenBudget, *, policy: str) -> None:
    """Raise when a shaped transcript still does not fit, instead of hiding it."""
    if tokens > budget.tokens:
        msg = f"{policy}: shaped context needs {tokens} tokens, budget is {budget.tokens}"
        raise ContextBudgetError(msg)
