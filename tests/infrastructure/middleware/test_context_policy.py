"""Offline tests for the LangChain context-policy middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage

from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.summary import SUMMARY_MESSAGE_PREFIX
from caio_code.domain.errors import ContextOverflowError
from caio_code.domain.events import ContextShaped, InMemoryEventBus
from caio_code.domain.policy.base import PolicyPipeline
from caio_code.domain.policy.compaction import CompactionPlanner
from caio_code.domain.policy.full_history import FullHistoryPolicy
from caio_code.domain.policy.sliding_window import SlidingWindowPolicy
from caio_code.domain.policy.structure_repair import StructureRepairPolicy
from caio_code.infrastructure.llm.stub import StubSummarizer
from caio_code.infrastructure.middleware.context_policy import ContextPolicyMiddleware
from caio_code.infrastructure.observability.bus import EventRecorder
from caio_code.infrastructure.observability.clocks import FixedClock
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter
from tests.application.compaction.test_service import PRICING

START = datetime(2026, 1, 1, tzinfo=UTC)
COUNTER = CharProxyTokenCounter()
BLOCK = "lorem ipsum dolor sit amet " * 8  # 216 chars -> 54 proxy tokens
Handler = Callable[[ModelRequest[Any]], Awaitable[Any]]


class FakeModel:
    """Stands in for the chat model; the middleware never touches it."""


class CapturingHandler:
    """Records the messages the middleware forwards and answers nothing."""

    def __init__(self) -> None:
        self.messages: list[AnyMessage] | None = None

    async def __call__(self, request: ModelRequest[Any]) -> str:
        self.messages = list(request.messages)
        return "ok"


def _request(messages: list[AnyMessage], *, system: str = "sys") -> ModelRequest[Any]:
    return ModelRequest(
        model=FakeModel(),  # type: ignore[arg-type]
        messages=messages,
        system_message=SystemMessage(content=system),
    )


def _chat_messages(count: int = 8) -> list[AnyMessage]:
    messages: list[AnyMessage] = [
        HumanMessage(content="the task statement", id="task"),
    ]
    for index in range(count):
        messages.append(AIMessage(content=f"{BLOCK}{index}", id=f"m{index}"))
    messages.append(HumanMessage(content="and the newest question", id="last"))
    return messages


def _middleware(
    pipeline: PolicyPipeline,
    *,
    budget: int,
    enforce: bool = False,
    with_compaction: bool = False,
) -> tuple[ContextPolicyMiddleware, EventRecorder]:
    bus = InMemoryEventBus()
    recorder = EventRecorder()
    bus.subscribe(recorder)
    compaction = None
    if with_compaction:
        from caio_code.application.compaction.service import CompactionService

        compaction = CompactionService(
            StubSummarizer(clock=FixedClock(START)),
            COUNTER,
            FixedClock(START),
            bus,
            PRICING,
        )
    middleware = ContextPolicyMiddleware(
        pipeline,
        counter=COUNTER,
        bus=bus,
        clock=FixedClock(START),
        budget=TokenBudget(budget),
        compaction=compaction,
        enforce_window=enforce,
        run_id="run-mw",
    )
    return middleware, recorder


async def test_middleware_shapes_messages_publishes_context_shaped_and_keeps_identity() -> None:
    messages = _chat_messages()
    middleware, recorder = _middleware(
        PolicyPipeline("window", [SlidingWindowPolicy(keep_recent_messages=2), StructureRepairPolicy()]),
        budget=120,
    )
    handler = CapturingHandler()

    await middleware.awrap_model_call(_request(messages), handler)

    shaped = recorder.of_type(ContextShaped)
    assert len(shaped) == 1
    assert isinstance(shaped[0], ContextShaped)
    assert shaped[0].decision is middleware.last_decision
    assert shaped[0].run_id == "run-mw"
    assert handler.messages is not None
    # Kept messages are the SAME LangChain objects (prompt-cache identity).
    assert len(handler.messages) == 3
    assert all(
        kept is original
        for kept, original in zip(handler.messages, messages[-3:], strict=True)
    )


async def test_enforce_window_raises_context_overflow_on_an_over_budget_transcript() -> None:
    messages = _chat_messages()
    middleware, _ = _middleware(
        PolicyPipeline("baseline", [FullHistoryPolicy(), StructureRepairPolicy()]),
        budget=50,
        enforce=True,
    )

    with pytest.raises(ContextOverflowError):
        await middleware.awrap_model_call(_request(messages), CapturingHandler())


async def test_compaction_service_replaces_the_placeholder_summary() -> None:
    messages = _chat_messages()
    middleware, _ = _middleware(
        PolicyPipeline("compact", [CompactionPlanner(keep_tokens=60), StructureRepairPolicy()]),
        budget=10_000,
        with_compaction=True,
    )
    handler = CapturingHandler()

    await middleware.awrap_model_call(_request(messages), handler)

    assert middleware.compactions == 1
    assert handler.messages is not None
    summaries = [
        message
        for message in handler.messages
        if isinstance(message.content, str) and SUMMARY_MESSAGE_PREFIX in message.content
    ]
    assert len(summaries) == 1
    assert "[summary pending]" not in summaries[0].content


async def test_without_a_compaction_service_the_placeholder_stays() -> None:
    messages = _chat_messages()
    middleware, _ = _middleware(
        PolicyPipeline("compact", [CompactionPlanner(keep_tokens=60), StructureRepairPolicy()]),
        budget=10_000,
    )
    handler = CapturingHandler()

    await middleware.awrap_model_call(_request(messages), handler)

    assert middleware.compactions == 0
    assert handler.messages is not None
    assert any("[summary pending]" in str(message.content) for message in handler.messages)


def test_sync_path_shapes_without_compaction() -> None:
    messages = _chat_messages()
    middleware, recorder = _middleware(
        PolicyPipeline("compact", [CompactionPlanner(keep_tokens=60), StructureRepairPolicy()]),
        budget=10_000,
        with_compaction=True,
    )
    seen: list[AnyMessage] = []

    def handler(request: ModelRequest[Any]) -> str:
        seen.extend(request.messages)
        return "ok"

    middleware.wrap_model_call(_request(messages), handler)

    assert middleware.compactions == 0
    assert len(recorder.of_type(ContextShaped)) == 1
    assert any("[summary pending]" in str(message.content) for message in seen)


def test_fixed_token_estimate_accounts_for_system_message_and_tool_schemas() -> None:
    messages: list[AnyMessage] = [HumanMessage(content="hi", id="h")]

    class SchemaTool:
        name = "read_file"
        args_schema: ClassVar[dict[str, str]] = {"path": "str"}

    class NamelessTool:
        name = "search"
        args_schema: ClassVar[None] = None

    middleware, _ = _middleware(
        PolicyPipeline("baseline", [FullHistoryPolicy()]), budget=10_000
    )
    request = _request(messages, system="abcd").override(
        tools=[SchemaTool(), NamelessTool()]
    )

    fixed = middleware._fixed_tokens(request)

    expected = (
        COUNTER.count_text("abcd")
        + COUNTER.count_text("read_file")
        + COUNTER.count_text(str({"path": "str"}))
        + COUNTER.count_text("search")
    )
    assert fixed == expected
    assert fixed > COUNTER.count_text("abcd")


def test_empty_message_list_is_passed_through_unchanged() -> None:
    middleware, recorder = _middleware(
        PolicyPipeline("baseline", [FullHistoryPolicy()]), budget=10_000
    )
    seen: list[AnyMessage] = []

    def handler(request: ModelRequest[Any]) -> str:
        seen.extend(request.messages)
        return "ok"

    middleware.wrap_model_call(_request([]), handler)

    assert seen == []
    assert recorder.events == []
    assert middleware.last_decision is None
