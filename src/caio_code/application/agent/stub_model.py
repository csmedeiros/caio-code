"""Deterministic chat model for the ``stub`` provider.

The deepagents graph needs a LangChain ``BaseChatModel``; the stub path must
never touch the network and must be reproducible byte for byte. This model
therefore answers from an explicit script of turns and, once the script is
exhausted, from one adaptive rule (summarize the last tool result, or call
``default_tool`` exactly once). Identifiers, ordering and usage numbers are all
derived from the injected clock/counter and a call index: no randomness, no
wall clock, no uuid.

Usage metadata follows the OpenAI shape the runner maps: ``usage_metadata``
with ``input_token_details.cache_read`` plus ``response_metadata.token_usage``
with ``prompt_tokens_details.cached_tokens``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict, PrivateAttr

from caio_code.domain.ports.time import Clock
from caio_code.domain.ports.tokenizer import TokenCounter

STUB_MODEL_NAME = "stub"
CALL_ID_TEMPLATE = "stub-call-{index:04d}"
MESSAGE_ID_TEMPLATE = "stub-ai-{index:04d}"
EXHAUSTED_TEXT_TEMPLATE = "stub: script exhausted after {calls} model call(s)."
TOOL_RESULT_TEXT_TEMPLATE = "stub: finished after {calls} model call(s); last tool result: {preview}"
TOOL_RESULT_PREVIEW_CHARS = 200
DEFAULT_LIST_TOOL = "list_directory"


@dataclass(frozen=True, slots=True)
class StubToolTurn:
    """A scripted turn that requests one tool call."""

    tool: str
    arguments: dict[str, Any]


StubTurn = str | StubToolTurn | AIMessage


def tool_turn(tool: str, arguments: dict[str, Any]) -> StubToolTurn:
    """Convenience constructor for a scripted tool-call turn."""
    return StubToolTurn(tool=tool, arguments=arguments)


def default_stub_turns() -> tuple[StubTurn, ...]:
    """The turn script the headless CLI stub run uses: list, then answer."""
    return (
        tool_turn(DEFAULT_LIST_TOOL, {"path": "."}),
        "",  # empty string means: adapt (summarize the tool result)
    )


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content) if content else ""


class StubChatModel(BaseChatModel):
    """Scripted, offline ``BaseChatModel``; the only model tests may use."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    clock: Any = None
    counter: Any = None
    stub_name: str = STUB_MODEL_NAME
    turns: tuple[StubTurn, ...] = ()
    cached_input_fraction: float = 0.0
    default_tool: tuple[str, dict[str, Any]] | None = None

    _call_index: int = PrivateAttr(default=0)
    _turn_index: int = PrivateAttr(default=0)
    _default_tool_used: bool = PrivateAttr(default=False)
    _seen: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "caio-code-stub"

    @property
    def calls(self) -> tuple[list[BaseMessage], ...]:
        """Every message list the graph handed to the model, for assertions."""
        return tuple(self._seen)

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> Any:
        """The stub accepts any tool binding unchanged; scripts drive behavior."""
        return self

    def _usage(self, messages: Sequence[BaseMessage], text: str) -> dict[str, Any]:
        input_tokens = 0
        if self.counter is not None:
            input_tokens = sum(self.counter.count_text(_message_text(m)) for m in messages)
        else:
            input_tokens = sum(math.ceil(len(_message_text(m)) / 4) for m in messages)
        output_tokens = (
            self.counter.count_text(text)
            if self.counter is not None
            else math.ceil(len(text) / 4)
        )
        cached = min(input_tokens, math.floor(input_tokens * self.cached_input_fraction))
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": {"cache_read": cached},
            "_cached": cached,
        }

    def _next_turn(self, messages: Sequence[BaseMessage]) -> AIMessage:
        self._call_index += 1
        index = self._call_index
        message_id = MESSAGE_ID_TEMPLATE.format(index=index)

        while self._turn_index < len(self.turns):
            turn = self.turns[self._turn_index]
            self._turn_index += 1
            if isinstance(turn, AIMessage):
                return AIMessage(
                    content=turn.content,
                    id=turn.id or message_id,
                    tool_calls=list(turn.tool_calls),
                    usage_metadata=self._usage_metadata(messages, _message_text(turn)),
                    response_metadata=self._response_metadata(),
                )
            if isinstance(turn, StubToolTurn):
                return self._tool_call_message(turn, messages, index, message_id)
            if isinstance(turn, str) and turn:
                return self._text_message(turn, messages, message_id)
            # Empty string: fall through to the adaptive rule below.
            break

        last_tool = next(
            (message for message in reversed(messages) if isinstance(message, ToolMessage)),
            None,
        )
        if last_tool is not None:
            preview = _message_text(last_tool)[:TOOL_RESULT_PREVIEW_CHARS]
            text = TOOL_RESULT_TEXT_TEMPLATE.format(calls=index, preview=preview)
            return self._text_message(text, messages, message_id)
        if self.default_tool is not None and not self._default_tool_used:
            self._default_tool_used = True
            name, arguments = self.default_tool
            return self._tool_call_message(
                StubToolTurn(tool=name, arguments=arguments), messages, index, message_id
            )
        return self._text_message(
            EXHAUSTED_TEXT_TEMPLATE.format(calls=index), messages, message_id
        )

    def _tool_call_message(
        self,
        turn: StubToolTurn,
        messages: Sequence[BaseMessage],
        index: int,
        message_id: str,
    ) -> AIMessage:
        call_id = CALL_ID_TEMPLATE.format(index=index)
        message = AIMessage(
            content="",
            id=message_id,
            tool_calls=[{"name": turn.tool, "args": dict(turn.arguments), "id": call_id}],
            response_metadata=self._response_metadata(),
        )
        message.usage_metadata = self._usage_metadata(messages, "")  # type: ignore[assignment]
        return message

    def _text_message(
        self, text: str, messages: Sequence[BaseMessage], message_id: str
    ) -> AIMessage:
        message = AIMessage(
            content=text,
            id=message_id,
            response_metadata=self._response_metadata(),
        )
        message.usage_metadata = self._usage_metadata(messages, text)  # type: ignore[assignment]
        return message

    def _usage_metadata(self, messages: Sequence[BaseMessage], text: str) -> dict[str, Any]:
        usage = self._usage(messages, text)
        cached = usage.pop("_cached")
        return {**usage, "input_token_details": {"cache_read": cached}}

    def _response_metadata(self) -> dict[str, Any]:
        cached_fraction = self.cached_input_fraction
        return {
            "model_name": self.stub_name,
            "finish_reason": "stop",
            "_stub_cached_fraction": cached_fraction,
        }

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        started = self.clock.monotonic_ms() if self.clock is not None else 0
        self._seen.append(list(messages))
        message = self._next_turn(messages)
        _attach_token_usage(message)
        latency_ms = 0
        if self.clock is not None:
            latency_ms = self.clock.monotonic_ms() - started
        generation = ChatGeneration(
            message=message,
            generation_info={"finish_reason": "stop", "latency_ms": latency_ms},
        )
        return ChatResult(generations=[generation])


def _attach_token_usage(message: AIMessage) -> None:
    """Mirror ``usage_metadata`` into the OpenAI-shaped ``token_usage`` block.

    The runner maps ``prompt_tokens_details.cached_tokens`` when present, and
    this is where the stub provides it, exactly like a real endpoint does.
    """
    usage = message.usage_metadata
    if not usage:
        return
    details = usage.get("input_token_details") or {}
    cached = details.get("cache_read", 0) if isinstance(details, dict) else 0
    message.response_metadata["token_usage"] = {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "prompt_tokens_details": {"cached_tokens": cached},
    }


def build_stub_chat_model(
    *,
    clock: Clock | None = None,
    counter: TokenCounter | None = None,
    turns: Sequence[StubTurn] = (),
    cached_input_fraction: float = 0.0,
    default_tool: tuple[str, dict[str, Any]] | None = (DEFAULT_LIST_TOOL, {"path": "."}),
) -> StubChatModel:
    """Factory used by the runner and the CLI for the stub provider."""
    return StubChatModel(
        clock=clock,
        counter=counter,
        turns=tuple(turns),
        cached_input_fraction=cached_input_fraction,
        default_tool=default_tool,
    )


__all__ = [
    "DEFAULT_LIST_TOOL",
    "STUB_MODEL_NAME",
    "StubChatModel",
    "StubToolTurn",
    "StubTurn",
    "build_stub_chat_model",
    "default_stub_turns",
    "tool_turn",
]
