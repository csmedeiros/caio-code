"""Offline tests for the compaction use case (plan -> summarize -> replace)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from caio_code.application.compaction.service import CompactionService
from caio_code.config import ModelPrice
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.conversation.summary import SUMMARY_MESSAGE_PREFIX
from caio_code.domain.errors import SummarizerError
from caio_code.domain.events import CompactionEnded, CompactionStarted, InMemoryEventBus
from caio_code.domain.policy.base import PolicyDecision, PolicyRequest
from caio_code.domain.policy.compaction import SUMMARY_PLACEHOLDER, CompactionPlanner
from caio_code.domain.ports.summarizer import SummaryResult
from caio_code.domain.usage.accounting import PriceSheet, TokenUsage
from caio_code.infrastructure.llm.stub import StubSummarizer
from caio_code.infrastructure.observability.bus import EventRecorder
from caio_code.infrastructure.observability.clocks import FixedClock
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

START = datetime(2026, 1, 1, tzinfo=UTC)
COUNTER = CharProxyTokenCounter()
STUB_PRICE = ModelPrice("stub", Decimal("2"), Decimal("1"), Decimal("4"))
PRICING = PriceSheet(prices=(STUB_PRICE,))
FILLER = "alpha bravo charlie delta echo foxtrot"


class EmptySummarizer:
    """A summarizer that always answers with an empty string."""

    def _result(self) -> SummaryResult:
        return SummaryResult(text="", model="stub", usage=TokenUsage())

    async def asummarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        return self._result()

    def summarize(self, prompt: str, *, max_tokens: int) -> SummaryResult:
        return self._result()


def _transcript() -> Transcript:
    messages = [Message(id="task", role=Role.USER, text="the task", pinned=True)]
    messages.extend(
        Message(id=f"m{i}", role=Role.USER, text=FILLER) for i in range(30)
    )
    return Transcript.of(messages)


def _planned() -> tuple[Transcript, PolicyRequest, PolicyDecision]:
    transcript = _transcript()
    request = PolicyRequest(
        transcript=transcript, budget=TokenBudget(10_000), counter=COUNTER
    )
    decision = CompactionPlanner(keep_tokens=60).plan(request)
    return transcript, request, decision


def _service(summarizer: object | None = None) -> tuple[CompactionService, EventRecorder]:
    bus = InMemoryEventBus()
    recorder = EventRecorder()
    bus.subscribe(recorder)
    service = CompactionService(
        summarizer or StubSummarizer(clock=FixedClock(START)),
        COUNTER,
        FixedClock(START, step_ms=100),
        bus,
        PRICING,
    )
    return service, recorder


async def test_compact_publishes_started_then_ended_and_returns_a_well_formed_summary() -> None:
    transcript, request, decision = _planned()
    service, recorder = _service()

    outcome = await service.compact(
        transcript=transcript, request=request, decision=decision, run_id="run-1"
    )

    started = recorder.of_type(CompactionStarted)
    ended = recorder.of_type(CompactionEnded)
    assert len(started) == 1 and len(ended) == 1
    assert recorder.events.index(started[0]) < recorder.events.index(ended[0])
    assert outcome.well_formed
    assert outcome.summary.is_well_formed
    assert ended[0].well_formed is True


async def test_compact_returns_a_pinned_replacement_message_with_the_real_summary() -> None:
    transcript, request, decision = _planned()
    service, _ = _service()

    outcome = await service.compact(
        transcript=transcript, request=request, decision=decision, run_id="run-1"
    )

    message = outcome.message
    assert message.pinned
    assert message.text.startswith(SUMMARY_MESSAGE_PREFIX)
    assert SUMMARY_PLACEHOLDER not in message.text
    assert outcome.summary.render() in message.text


async def test_compact_accounts_usage_and_prices_cost_with_the_injected_sheet() -> None:
    transcript, request, decision = _planned()
    service, _ = _service()

    outcome = await service.compact(
        transcript=transcript, request=request, decision=decision, run_id="run-1"
    )

    assert outcome.usage.total_tokens > 0
    assert outcome.cost == PRICING.cost_of(outcome.usage, "stub")
    assert outcome.cost.usd > 0
    assert outcome.latency_ms > 0


async def test_tokens_after_is_measured_on_the_replaced_transcript() -> None:
    transcript, request, decision = _planned()
    service, _ = _service()

    outcome = await service.compact(
        transcript=transcript, request=request, decision=decision, run_id="run-1"
    )

    replaced = Transcript.of(
        outcome.message if SUMMARY_PLACEHOLDER in item.text else item
        for item in decision.result(transcript)
    )
    assert outcome.tokens_after == COUNTER.count_transcript(replaced)
    assert outcome.tokens_after < outcome.tokens_before
    assert outcome.tokens_after != decision.tokens_after


async def test_empty_summarizer_output_yields_a_not_well_formed_summary_without_raising() -> None:
    transcript, request, decision = _planned()
    service, _ = _service(summarizer=EmptySummarizer())

    outcome = await service.compact(
        transcript=transcript, request=request, decision=decision, run_id="run-1"
    )

    assert outcome.well_formed is False
    assert outcome.summary.sections == ()


async def test_compact_sync_raises_summarizer_error_inside_a_running_loop() -> None:
    transcript, request, decision = _planned()
    service, _ = _service()

    with pytest.raises(SummarizerError, match="running event loop"):
        service.compact_sync(
            transcript=transcript, request=request, decision=decision, run_id="run-1"
        )


def test_compact_sync_runs_from_a_synchronous_caller() -> None:
    transcript, request, decision = _planned()
    service, recorder = _service()

    outcome = service.compact_sync(
        transcript=transcript, request=request, decision=decision, run_id="run-1"
    )

    assert outcome.well_formed
    assert len(recorder.of_type(CompactionEnded)) == 1


async def test_decision_without_an_injected_prompt_raises_summarizer_error() -> None:
    service, _ = _service()
    decision = PolicyDecision(
        policy="no_prompt", kept_indices=(0,), counter=COUNTER, injected=()
    )

    with pytest.raises(SummarizerError, match="no prompt"):
        await service.compact(
            transcript=_transcript(),
            request=PolicyRequest(
                transcript=_transcript(), budget=TokenBudget(100), counter=COUNTER
            ),
            decision=decision,
            run_id="run-1",
        )
