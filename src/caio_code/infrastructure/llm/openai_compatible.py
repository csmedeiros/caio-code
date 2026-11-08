"""Model gateway over any OpenAI-compatible endpoint, using the ``openai`` SDK.

This is the adapter the experiment runs against (the Aliyun endpoint configured
through ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``). LangChain is deliberately not
used here: the domain speaks :class:`Message`, and this module is the only place
that knows the wire format.

Invariants:

- Retries are bounded by ``max_retries`` (from :class:`ProviderConfig`) and wait
  a fixed, injected delay; nothing here sleeps on its own schedule.
- Latency is measured with the injected :class:`Clock`, never ``time.time()``.
- Transport and auth failures surface as :class:`ProviderError`; missing
  credentials as :class:`ConfigurationError`. Error messages never contain the
  API key.
- Usage mapping is defensive: ``usage``, ``prompt_tokens_details`` and
  ``cached_tokens`` may all be absent depending on the endpoint.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from openai import AsyncOpenAI, OpenAI, OpenAIError

from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.errors import ConfigurationError, ProviderError, SummarizerError
from caio_code.domain.ports.gateway import ModelGateway, ModelReply, ToolSchema
from caio_code.domain.ports.scorer import RelevanceScorer, ScoredMessage
from caio_code.domain.ports.summarizer import Summarizer, SummaryResult
from caio_code.domain.ports.time import Clock
from caio_code.domain.usage.accounting import TokenUsage

RETRY_DELAY_SECONDS = 2.0
"""Fixed delay between retries; tests inject their own ``sleep`` to skip it."""

SUMMARY_PROMPT_MESSAGE_ID = "summary-prompt"
SCORER_PROMPT_MESSAGE_ID = "scorer-prompt"
SCORER_MESSAGE_CHAR_CAP = 2_000
"""Characters of each message shown to the scorer, matching the tool-result cap."""

_SCORES_INSTRUCTION = (
    "Score how relevant each numbered message is to the task. "
    "Reply with ONLY a JSON object of the exact form {\"scores\": [<float>, ...]} "
    "with one score per message, in order. No prose, no code fences."
)


def message_payloads(messages: Sequence[Message], system: str | None) -> list[dict[str, Any]]:
    """Domain messages as OpenAI chat-completion payloads."""
    payloads: list[dict[str, Any]] = []
    if system:
        payloads.append({"role": "system", "content": system})
    for message in messages:
        if message.role is Role.SYSTEM:
            payloads.append({"role": "system", "content": message.text})
        elif message.role is Role.USER:
            payloads.append({"role": "user", "content": message.text})
        elif message.role is Role.ASSISTANT:
            entry: dict[str, Any] = {"role": "assistant", "content": message.text or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in message.tool_calls
                ]
            payloads.append(entry)
        else:
            payloads.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id or "",
                    "content": message.text,
                }
            )
    return payloads


def tool_payloads(tools: Sequence[ToolSchema] | None) -> list[dict[str, Any]] | None:
    """Domain tool schemas as OpenAI function-tool payloads."""
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


def tool_calls_from_response(response: Any) -> tuple[ToolCall, ...]:
    """Map the reply's tool calls defensively; the field may be absent or null."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ()
    raw_calls = getattr(choices[0].message, "tool_calls", None) or []
    calls: list[ToolCall] = []
    for call in raw_calls:
        function = getattr(call, "function", None)
        if function is None:
            continue
        calls.append(
            ToolCall(
                id=getattr(call, "id", "") or "",
                name=getattr(function, "name", "") or "",
                arguments=getattr(function, "arguments", "") or "{}",
            )
        )
    return tuple(calls)


def usage_from_response(response: Any) -> TokenUsage:
    """Map provider usage defensively; every field may be missing."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()
    input_tokens = max(0, int(getattr(usage, "prompt_tokens", 0) or 0))
    output_tokens = max(0, int(getattr(usage, "completion_tokens", 0) or 0))
    details = getattr(usage, "prompt_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
    cached = max(0, min(cached, input_tokens))
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached,
    )


class OpenAICompatibleGateway(ModelGateway):
    """``ModelGateway`` over the OpenAI chat-completions contract."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        clock: Clock,
        temperature: float = 0.0,
        max_output_tokens: int = 4_096,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        retry_delay_seconds: float = RETRY_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not base_url.strip():
            msg = "OpenAICompatibleGateway requires a base URL (set OPENAI_BASE_URL)"
            raise ConfigurationError(msg)
        if not api_key.strip():
            msg = "OpenAICompatibleGateway requires an API key (set OPENAI_API_KEY)"
            raise ConfigurationError(msg)
        self._model = model
        self._clock = clock
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._sleep = sleep
        self._async_sleep = async_sleep
        client_kwargs = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": timeout_seconds,
            "max_retries": 0,  # the SDK must not retry behind the measured loop
        }
        self._client = OpenAI(**client_kwargs)
        self._async_client = AsyncOpenAI(**client_kwargs)

    @property
    def model(self) -> str:
        return self._model

    def _request_kwargs(
        self,
        messages: Sequence[Message],
        *,
        system: str | None,
        max_tokens: int | None,
        temperature: float | None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": message_payloads(messages, system),
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_output_tokens if max_tokens is None else max_tokens,
        }
        payloads = tool_payloads(tools)
        if payloads is not None:
            kwargs["tools"] = payloads
        return kwargs

    def _attempts_made(self, last_error: BaseException | None) -> int:
        """How many attempts were really spent: one when the error is not retryable."""
        if last_error is not None and not is_retryable(last_error):
            return 1
        return self._max_retries + 1

    def _reply_from(self, response: Any, latency_ms: int) -> ModelReply:
        choices = getattr(response, "choices", None) or []
        text = ""
        finish_reason = "stop"
        if choices:
            text = getattr(choices[0].message, "content", None) or ""
            finish_reason = getattr(choices[0], "finish_reason", None) or "stop"
        return ModelReply(
            text=text,
            usage=usage_from_response(response),
            model=getattr(response, "model", None) or self._model,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            tool_calls=tool_calls_from_response(response),
            raw={"id": getattr(response, "id", "")},
        )

    def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        kwargs = self._request_kwargs(
            messages, system=system, max_tokens=max_tokens, temperature=temperature, tools=tools
        )
        started_at = self._clock.monotonic_ms()
        last_error: OpenAIError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(**kwargs)
            except OpenAIError as exc:
                last_error = exc
                if attempt < self._max_retries and is_retryable(exc):
                    self._sleep(self._retry_delay_seconds)
                    continue
                break
            return self._reply_from(response, self._clock.monotonic_ms() - started_at)
        attempts = self._attempts_made(last_error)
        msg = f"model call to {self._model!r} failed after {attempts} attempts: {describe(last_error)}"
        raise ProviderError(msg) from last_error

    async def acomplete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        tools: Sequence[ToolSchema] | None = None,
    ) -> ModelReply:
        kwargs = self._request_kwargs(
            messages, system=system, max_tokens=max_tokens, temperature=temperature, tools=tools
        )
        started_at = self._clock.monotonic_ms()
        last_error: OpenAIError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._async_client.chat.completions.create(**kwargs)
            except OpenAIError as exc:
                last_error = exc
                if attempt < self._max_retries and is_retryable(exc):
                    await self._async_sleep(self._retry_delay_seconds)
                    continue
                break
            return self._reply_from(response, self._clock.monotonic_ms() - started_at)
        attempts = self._attempts_made(last_error)
        msg = f"model call to {self._model!r} failed after {attempts} attempts: {describe(last_error)}"
        raise ProviderError(msg) from last_error


RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})
"""Statuses worth another attempt: request timeout, conflict and rate limit."""


def is_retryable(exc: BaseException) -> bool:
    """Retry transport and throttling failures only.

    A 400 means the request itself is wrong - an orphan tool result, a message
    the endpoint refuses - and sending it again wastes minutes and money while
    producing the same rejection.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS_CODES or status >= 500
    name = type(exc).__name__
    return name in {"APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError"}


def describe(exc: BaseException) -> str:
    """The provider's own message, so a 400 body reaches the report."""
    body = getattr(exc, "body", None)
    status = getattr(exc, "status_code", None)
    parts = [type(exc).__name__]
    if status is not None:
        parts.append(f"status {status}")
    detail = str(getattr(exc, "message", "") or exc)
    if detail:
        parts.append(detail[:600])
    if isinstance(body, dict):
        parts.append(str(body)[:600])
    return " | ".join(parts)


class OpenAICompatibleSummarizer(Summarizer):
    """Adapts any :class:`ModelGateway` into the summarizer port."""

    def __init__(self, *, gateway: ModelGateway) -> None:
        self._gateway = gateway

    def _result(self, reply: ModelReply) -> SummaryResult:
        if reply.is_empty:
            msg = f"summarizer model {reply.model!r} returned an empty summary"
            raise SummarizerError(msg)
        return SummaryResult(
            text=reply.text,
            model=reply.model,
            usage=reply.usage,
            latency_ms=reply.latency_ms,
        )

    def _prompt_message(self, prompt: str) -> Message:
        return Message(id=SUMMARY_PROMPT_MESSAGE_ID, role=Role.USER, text=prompt)

    async def asummarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        reply = await self._gateway.acomplete(
            [self._prompt_message(prompt)], max_tokens=max_tokens
        )
        return self._result(reply)

    def summarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        reply = self._gateway.complete([self._prompt_message(prompt)], max_tokens=max_tokens)
        return self._result(reply)


def scorer_prompt(task: str, messages: Sequence[Message]) -> str:
    """Numbered messages plus the strict-JSON instruction."""
    lines = [f"Task: {task}", "", "Messages:"]
    for index, message in enumerate(messages):
        text = message.text[:SCORER_MESSAGE_CHAR_CAP]
        lines.append(f"[{index}] {message.role.value}: {text}")
    lines.append("")
    lines.append(_SCORES_INSTRUCTION)
    return "\n".join(lines)


def parse_scores_payload(text: str, *, expected: int) -> list[float]:
    """Parse the strict ``{"scores": [...]}`` reply.

    Raises :class:`ValueError` when the payload is missing, unparseable, or has
    the wrong length; the caller degrades to its fallback instead of raising.
    """
    cleaned = text.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        msg = f"scorer reply is not a JSON object: {cleaned[:80]!r}"
        raise ValueError(msg)
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict) or "scores" not in payload:
        msg = "scorer reply has no 'scores' key"
        raise ValueError(msg)
    scores = payload["scores"]
    if not isinstance(scores, list) or len(scores) != expected:
        msg = f"scorer returned {len(scores) if isinstance(scores, list) else 'non-list'} for {expected} messages"
        raise ValueError(msg)
    return [float(score) for score in scores]


class ModelRelevanceScorer(RelevanceScorer):
    """Asks the auxiliary model for scores; degrades to ``fallback`` on failure."""

    def __init__(self, *, gateway: ModelGateway, fallback: RelevanceScorer) -> None:
        self._gateway = gateway
        self._fallback = fallback

    @property
    def name(self) -> str:
        return f"model/{self._gateway.model}"

    def _scored(self, messages: Sequence[Message], scores: Sequence[float]) -> list[ScoredMessage]:
        return [
            ScoredMessage(index=index, score=score, message=message)
            for index, (message, score) in enumerate(zip(messages, scores, strict=True))
        ]

    def _prompt_messages(self, task: str, messages: Sequence[Message]) -> list[Message]:
        return [
            Message(
                id=SCORER_PROMPT_MESSAGE_ID,
                role=Role.USER,
                text=scorer_prompt(task, messages),
            )
        ]

    async def ascore(
        self,
        *,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        if not messages:
            return []
        try:
            reply = await self._gateway.acomplete(self._prompt_messages(task, messages))
            scores = parse_scores_payload(reply.text, expected=len(messages))
        except (ProviderError, ValueError, TypeError):
            return await self._fallback.ascore(task=task, messages=messages)
        return self._scored(messages, scores)

    def score(
        self,
        *,
        task: str,
        messages: Sequence[Message],
    ) -> Sequence[ScoredMessage]:
        if not messages:
            return []
        try:
            reply = self._gateway.complete(self._prompt_messages(task, messages))
            scores = parse_scores_payload(reply.text, expected=len(messages))
        except (ProviderError, ValueError, TypeError):
            return self._fallback.score(task=task, messages=messages)
        return self._scored(messages, scores)
