"""Offline tests for the OpenAI-compatible adapters.

The real ``openai`` clients are replaced by fakes after construction; no test
here touches the network. The single integration test is skipped by default.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError

from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.errors import ConfigurationError, ProviderError, SummarizerError
from caio_code.domain.ports.scorer import ScoredMessage
from caio_code.infrastructure.llm.openai_compatible import (
    RETRY_DELAY_SECONDS,
    ModelRelevanceScorer,
    OpenAICompatibleGateway,
    OpenAICompatibleSummarizer,
    parse_scores_payload,
    usage_from_response,
)
from caio_code.infrastructure.llm.stub import StubGateway, StubScorer
from caio_code.infrastructure.observability.clocks import FixedClock

START = datetime(2026, 1, 1, tzinfo=UTC)
BASE_URL = "http://localhost:1/v1"
API_KEY = "test-key"


def _response(
    text: str = "ok",
    *,
    prompt_tokens: int | None = 10,
    completion_tokens: int | None = 5,
    cached_tokens: int | None = 2,
    with_details: bool = True,
    model: str = "fake-model",
) -> SimpleNamespace:
    if prompt_tokens is None:
        usage: Any = None
    else:
        details = (
            SimpleNamespace(cached_tokens=cached_tokens) if with_details and cached_tokens else None
        )
        usage = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_tokens_details=details,
        )
    return SimpleNamespace(
        id="resp-1",
        model=model,
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")
        ],
        usage=usage,
    )


def _connection_error() -> APIConnectionError:
    return APIConnectionError(request=httpx.Request("POST", BASE_URL))


class _FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def _next(self, kwargs: dict[str, Any]) -> Any:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def create(self, **kwargs: Any) -> Any:
        return self._next(kwargs)

    async def acreate(self, **kwargs: Any) -> Any:
        return self._next(kwargs)


def _install(gateway: OpenAICompatibleGateway, outcomes: list[Any]) -> _FakeCompletions:
    fake = _FakeCompletions(outcomes)
    completions = SimpleNamespace(create=fake.create)
    async_completions = SimpleNamespace(create=fake.acreate)
    gateway._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )
    gateway._async_client = SimpleNamespace(
        chat=SimpleNamespace(completions=async_completions)
    )
    return fake


def _gateway(**kwargs: Any) -> OpenAICompatibleGateway:
    defaults: dict[str, Any] = {
        "base_url": BASE_URL,
        "api_key": API_KEY,
        "model": "fake-model",
        "clock": FixedClock(START, step_ms=10),
    }
    defaults.update(kwargs)
    return OpenAICompatibleGateway(**defaults)


def _user(text: str, message_id: str = "u1") -> Message:
    return Message(id=message_id, role=Role.USER, text=text)


class TestGatewayConstruction:
    def test_missing_base_url_raises_configuration_error(self) -> None:
        with pytest.raises(ConfigurationError, match="OPENAI_BASE_URL"):
            _gateway(base_url="  ")

    def test_missing_api_key_raises_configuration_error(self) -> None:
        with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
            _gateway(api_key="")


class TestComplete:
    def test_happy_path_maps_reply_and_usage(self) -> None:
        gateway = _gateway()
        fake = _install(gateway, [_response("hello", prompt_tokens=7, completion_tokens=3, cached_tokens=2)])
        reply = gateway.complete([_user("hi")], system="be terse")
        assert reply.text == "hello"
        assert reply.model == "fake-model"
        assert reply.finish_reason == "stop"
        assert reply.usage.input_tokens == 7
        assert reply.usage.output_tokens == 3
        assert reply.usage.cached_input_tokens == 2
        assert reply.latency_ms == 10
        payload = fake.calls[0]
        assert payload["messages"][0] == {"role": "system", "content": "be terse"}
        assert payload["messages"][1] == {"role": "user", "content": "hi"}

    def test_payload_covers_every_role(self) -> None:
        gateway = _gateway()
        fake = _install(gateway, [_response()])
        messages = [
            Message(id="s", role=Role.SYSTEM, text="sys"),
            Message(
                id="a",
                role=Role.ASSISTANT,
                text="",
                tool_calls=(ToolCall(id="t1", name="ls", arguments='{"p": 1}'),),
            ),
            Message(id="t", role=Role.TOOL, text="result", tool_call_id="t1", name="ls"),
        ]
        gateway.complete(messages)
        payload = fake.calls[0]["messages"]
        assert payload[0]["role"] == "system"
        assert payload[1]["role"] == "assistant"
        assert payload[1]["tool_calls"][0]["function"] == {
            "name": "ls",
            "arguments": '{"p": 1}',
        }
        assert payload[2] == {"role": "tool", "tool_call_id": "t1", "content": "result"}

    def test_missing_usage_is_mapped_to_zeros(self) -> None:
        gateway = _gateway()
        _install(gateway, [_response(prompt_tokens=None)])
        reply = gateway.complete([_user("hi")])
        assert reply.usage.input_tokens == 0
        assert reply.usage.output_tokens == 0

    def test_absent_cached_tokens_is_zero(self) -> None:
        assert usage_from_response(_response(with_details=False)).cached_input_tokens == 0
        assert usage_from_response(_response(cached_tokens=None)).cached_input_tokens == 0

    def test_cached_tokens_larger_than_input_are_clamped(self) -> None:
        usage = usage_from_response(_response(prompt_tokens=4, cached_tokens=99))
        assert usage.cached_input_tokens == 4

    def test_empty_choices_yields_empty_text(self) -> None:
        gateway = _gateway()
        bare = SimpleNamespace(id="r", model="m", choices=[], usage=None)
        _install(gateway, [bare])
        reply = gateway.complete([_user("hi")])
        assert reply.text == ""
        assert reply.is_empty

    def test_per_call_overrides_reach_the_wire(self) -> None:
        gateway = _gateway(temperature=0.1, max_output_tokens=64)
        fake = _install(gateway, [_response()])
        gateway.complete([_user("hi")], max_tokens=32, temperature=0.7)
        assert fake.calls[0]["max_tokens"] == 32
        assert fake.calls[0]["temperature"] == 0.7

    def test_defaults_come_from_the_constructor(self) -> None:
        gateway = _gateway(temperature=0.1, max_output_tokens=64)
        fake = _install(gateway, [_response()])
        gateway.complete([_user("hi")])
        assert fake.calls[0]["max_tokens"] == 64
        assert fake.calls[0]["temperature"] == 0.1

    async def test_acomplete_happy_path(self) -> None:
        gateway = _gateway()
        _install(gateway, [_response("async-hello")])
        reply = await gateway.acomplete([_user("hi")])
        assert reply.text == "async-hello"


class TestRetries:
    def test_recovers_after_transient_failures(self) -> None:
        gateway = _gateway(max_retries=2, retry_delay_seconds=RETRY_DELAY_SECONDS)
        fake = _install(gateway, [_connection_error(), _connection_error(), _response("late")])
        slept: list[float] = []
        gateway._sleep = slept.append
        reply = gateway.complete([_user("hi")])
        assert reply.text == "late"
        assert len(fake.calls) == 3
        assert slept == [RETRY_DELAY_SECONDS, RETRY_DELAY_SECONDS]

    def test_exhausted_retries_raise_provider_error(self) -> None:
        gateway = _gateway(max_retries=1)
        fake = _install(gateway, [_connection_error()])
        slept: list[float] = []
        gateway._sleep = slept.append
        with pytest.raises(ProviderError, match="after 2 attempts"):
            gateway.complete([_user("hi")])
        assert len(fake.calls) == 2
        assert slept == [RETRY_DELAY_SECONDS]

    def test_zero_retries_fails_on_first_error(self) -> None:
        gateway = _gateway(max_retries=0)
        fake = _install(gateway, [_connection_error()])
        with pytest.raises(ProviderError):
            gateway.complete([_user("hi")])
        assert len(fake.calls) == 1

    async def test_async_exhausted_retries_raise_provider_error(self) -> None:
        gateway = _gateway(max_retries=1)
        fake = _install(gateway, [_connection_error()])
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        gateway._async_sleep = fake_sleep
        with pytest.raises(ProviderError):
            await gateway.acomplete([_user("hi")])
        assert len(fake.calls) == 2
        assert slept == [RETRY_DELAY_SECONDS]


class TestSummarizer:
    def test_empty_output_raises_summarizer_error(self) -> None:
        summarizer = OpenAICompatibleSummarizer(
            gateway=StubGateway(clock=FixedClock(START), replies=["   "])
        )
        with pytest.raises(SummarizerError):
            summarizer.summarize("prompt", max_tokens=128)

    def test_honours_max_tokens_and_passes_usage(self) -> None:
        gateway = _gateway()
        fake = _install(gateway, [_response("## Objective\n- x", prompt_tokens=9, completion_tokens=4)])
        summarizer = OpenAICompatibleSummarizer(gateway=gateway)
        result = summarizer.summarize("the prompt", max_tokens=77)
        assert fake.calls[0]["max_tokens"] == 77
        assert result.text.startswith("## Objective")
        assert result.usage.input_tokens == 9
        assert result.model == "fake-model"

    async def test_asummarize(self) -> None:
        gateway = _gateway()
        _install(gateway, [_response("summary")])
        summarizer = OpenAICompatibleSummarizer(gateway=gateway)
        result = await summarizer.asummarize("p", max_tokens=10)
        assert result.text == "summary"


class TestModelRelevanceScorer:
    def _fallback(self) -> StubScorer:
        return StubScorer(name="fallback")

    def test_parses_strict_json_scores(self) -> None:
        gateway = StubGateway(
            clock=FixedClock(START), replies=['{"scores": [0.9, 0.1, 0.5]}']
        )
        scorer = ModelRelevanceScorer(gateway=gateway, fallback=self._fallback())
        messages = [_user("a", "m0"), _user("b", "m1"), _user("c", "m2")]
        scored = scorer.score(task="task", messages=messages)
        assert [item.score for item in scored] == [0.9, 0.1, 0.5]
        assert [item.index for item in scored] == [0, 1, 2]
        assert all(isinstance(item, ScoredMessage) for item in scored)

    def test_unparseable_json_uses_fallback(self) -> None:
        gateway = StubGateway(clock=FixedClock(START), replies=["not json at all"])
        scorer = ModelRelevanceScorer(gateway=gateway, fallback=self._fallback())
        messages = [_user("task words here", "m0"), _user("other", "m1")]
        scored = scorer.score(task="task words", messages=messages)
        assert [item.index for item in scored] == [0, 1]
        assert scored[0].score > scored[1].score

    def test_wrong_length_scores_use_fallback(self) -> None:
        gateway = StubGateway(clock=FixedClock(START), replies=['{"scores": [0.5]}'])
        scorer = ModelRelevanceScorer(gateway=gateway, fallback=self._fallback())
        scored = scorer.score(task="t", messages=[_user("a", "m0"), _user("b", "m1")])
        assert len(scored) == 2

    def test_transport_failure_uses_fallback(self) -> None:
        gateway = _gateway(max_retries=0)
        _install(gateway, [_connection_error()])
        gateway._sleep = lambda _seconds: None
        scorer = ModelRelevanceScorer(gateway=gateway, fallback=self._fallback())
        scored = scorer.score(task="task", messages=[_user("task", "m0")])
        assert len(scored) == 1

    def test_zero_length_input_returns_empty_without_calling_model(self) -> None:
        gateway = StubGateway(clock=FixedClock(START), replies=["never used"])
        scorer = ModelRelevanceScorer(gateway=gateway, fallback=self._fallback())
        assert scorer.score(task="t", messages=[]) == []

    async def test_ascore_parses(self) -> None:
        gateway = StubGateway(clock=FixedClock(START), replies=['{"scores": [1.0]}'])
        scorer = ModelRelevanceScorer(gateway=gateway, fallback=self._fallback())
        scored = await scorer.ascore(task="t", messages=[_user("a", "m0")])
        assert scored[0].score == 1.0


class TestParseScoresPayload:
    def test_accepts_code_fenced_json(self) -> None:
        assert parse_scores_payload('```json\n{"scores": [0.5]}\n```', expected=1) == [0.5]

    def test_rejects_missing_key(self) -> None:
        with pytest.raises(ValueError, match="scores"):
            parse_scores_payload('{"values": [0.5]}', expected=1)

    def test_rejects_non_numeric_entries(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            parse_scores_payload('{"scores": ["high"]}', expected=1)

    def test_rejects_empty_object(self) -> None:
        with pytest.raises(ValueError):
            parse_scores_payload("", expected=0)


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("CAIO_CODE_RUN_INTEGRATION") != "1",
    reason="set CAIO_CODE_RUN_INTEGRATION=1 with real credentials to run",
)
def test_live_endpoint_round_trip() -> None:  # pragma: no cover - needs network
    from caio_code.config import load_settings
    from caio_code.infrastructure.llm.factory import build_gateway
    from caio_code.infrastructure.observability.clocks import SystemClock

    settings = load_settings(provider="openai_compatible")
    gateway = build_gateway(settings, clock=SystemClock())
    reply = gateway.complete([_user("reply with the single word: pong")])
    assert reply.text.strip()
    assert reply.usage.total_tokens > 0
