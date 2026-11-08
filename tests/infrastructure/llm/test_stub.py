"""Offline tests for the deterministic stub adapters."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from caio_code.domain.conversation.messages import Message, Role
from caio_code.domain.conversation.summary import parse_summary, summarizer_prompt
from caio_code.domain.errors import ConfigurationError
from caio_code.infrastructure.llm.stub import StubGateway, StubScorer, StubSummarizer
from caio_code.infrastructure.observability.clocks import FixedClock

START = datetime(2026, 1, 1, tzinfo=UTC)


def _clock() -> FixedClock:
    return FixedClock(START, step_ms=100)


def _user(text: str, message_id: str = "u1") -> Message:
    return Message(id=message_id, role=Role.USER, text=text)


class TestStubGateway:
    def test_round_robin_cycles_replies(self) -> None:
        gateway = StubGateway(clock=_clock(), replies=["a", "b"])
        messages = [_user("hi")]
        assert gateway.complete(messages).text == "a"
        assert gateway.complete(messages).text == "b"
        assert gateway.complete(messages).text == "a"

    def test_keyword_reply_wins_over_round_robin(self) -> None:
        gateway = StubGateway(
            clock=_clock(),
            replies=["generic"],
            keyword_replies={"compact": "summary-reply"},
        )
        reply = gateway.complete([_user("please compact the history")])
        assert reply.text == "summary-reply"
        # Round-robin position is untouched by a keyword hit.
        assert gateway.complete([_user("other")]).text == "generic"

    def test_last_user_message_drives_keyword_match(self) -> None:
        gateway = StubGateway(clock=_clock(), keyword_replies={"compact": "hit"})
        messages = [_user("compact now", "u1"), _user("unrelated", "u2")]
        assert gateway.complete(messages).text == ""

    def test_no_replies_configured_yields_empty_reply(self) -> None:
        gateway = StubGateway(clock=_clock())
        reply = gateway.complete([_user("hi")])
        assert reply.text == ""
        assert reply.is_empty

    def test_usage_is_char_proxy(self) -> None:
        gateway = StubGateway(clock=_clock(), replies=["xxxx"])
        reply = gateway.complete([_user("x" * 40)], system="y" * 8)
        # 40 chars -> 10 tokens, plus 8 system chars -> 2 tokens; "xxxx" -> 1.
        assert reply.usage.input_tokens == 12
        assert reply.usage.output_tokens == 1
        assert reply.usage.cached_input_tokens == 0

    def test_cached_fraction_is_applied_and_capped(self) -> None:
        gateway = StubGateway(clock=_clock(), replies=["r"], cached_input_fraction=0.5)
        reply = gateway.complete([_user("x" * 40)])
        assert reply.usage.input_tokens == 10
        assert reply.usage.cached_input_tokens == 5

    def test_invalid_cached_fraction_raises_configuration_error(self) -> None:
        with pytest.raises(ConfigurationError):
            StubGateway(clock=_clock(), cached_input_fraction=1.5)

    def test_latency_comes_from_injected_clock(self) -> None:
        gateway = StubGateway(clock=FixedClock(START, step_ms=100), replies=["r"])
        reply = gateway.complete([_user("hi")])
        assert reply.latency_ms == 100

    async def test_acomplete_matches_complete(self) -> None:
        gateway = StubGateway(clock=_clock(), replies=["a", "b"])
        messages = [_user("hi")]
        first = await gateway.acomplete(messages)
        second = gateway.complete(messages)
        assert first.text == "a"
        assert second.text == "b"

    def test_empty_transcript_is_accepted(self) -> None:
        gateway = StubGateway(clock=_clock(), replies=["ok"])
        reply = gateway.complete([])
        assert reply.text == "ok"
        assert reply.usage.input_tokens == 0

    def test_model_attribute_is_exposed(self) -> None:
        gateway = StubGateway(clock=_clock(), model="stub-x")
        assert gateway.model == "stub-x"
        assert gateway.complete([_user("hi")]).model == "stub-x"


class TestStubSummarizer:
    def _prompt(self) -> str:
        return summarizer_prompt(
            conversation=[
                "[User]: fix the parser in src/parser.py",
                "[Assistant]: found the bug at line 42",
                "[Tool result (read)]: value = 42",
                "[Assistant]: next I will patch tests/test_parser.py",
            ],
        )

    def test_summary_is_well_formed(self) -> None:
        summarizer = StubSummarizer(clock=_clock())
        result = summarizer.summarize(self._prompt(), max_tokens=4_096)
        parsed = parse_summary(result.text)
        assert parsed.is_well_formed
        assert parsed.missing_sections() == ()

    def test_extracts_objective_details_files_and_next_move(self) -> None:
        summarizer = StubSummarizer(clock=_clock())
        parsed = parse_summary(summarizer.summarize(self._prompt(), max_tokens=4_096).text)
        assert "fix the parser in src/parser.py" in parsed.text_of("Objective")
        assert "value = 42" in parsed.text_of("Important Details")
        assert "src/parser.py" in parsed.text_of("Relevant Files")
        assert "tests/test_parser.py" in parsed.text_of("Next Move")
        assert parsed.text_of("Completed") == "- (none)"

    def test_empty_prompt_is_still_well_formed(self) -> None:
        summarizer = StubSummarizer(clock=_clock())
        result = summarizer.summarize("", max_tokens=4_096)
        parsed = parse_summary(result.text)
        assert parsed.is_well_formed
        assert "(none)" in parsed.text_of("Objective")

    def test_usage_and_latency_are_reported(self) -> None:
        summarizer = StubSummarizer(model="stub-sum", clock=FixedClock(START, step_ms=50))
        result = summarizer.summarize("[User]: hello", max_tokens=4_096)
        assert result.model == "stub-sum"
        assert result.usage.input_tokens == math.ceil(len("[User]: hello") / 4)
        assert result.usage.output_tokens > 0
        assert result.latency_ms == 50
        assert result.is_usable

    async def test_asummarize_matches_summarize(self) -> None:
        summarizer = StubSummarizer(clock=_clock())
        sync = summarizer.summarize(self._prompt(), max_tokens=4_096)
        async_result = await summarizer.asummarize(self._prompt(), max_tokens=4_096)
        assert async_result.text == sync.text


class TestStubScorer:
    def test_one_score_per_message_with_overlap(self) -> None:
        scorer = StubScorer()
        messages = [
            _user("fix the parser", "m0"),
            _user("completely unrelated words here", "m1"),
        ]
        scored = scorer.score(task="fix the parser", messages=messages)
        assert len(scored) == 2
        best = scored[0]
        assert best.index == 0
        # overlap 3 words / sqrt(3 words)
        assert best.score == pytest.approx(3 / math.sqrt(3))

    def test_ties_break_by_recency(self) -> None:
        scorer = StubScorer()
        messages = [_user("alpha beta", "m0"), _user("alpha beta", "m1")]
        scored = scorer.score(task="alpha beta gamma", messages=messages)
        assert [item.index for item in scored] == [1, 0]

    def test_empty_message_scores_zero(self) -> None:
        scorer = StubScorer()
        scored = scorer.score(task="anything", messages=[_user("", "m0")])
        assert scored[0].score == 0.0

    def test_empty_task_scores_everything_zero(self) -> None:
        scorer = StubScorer()
        scored = scorer.score(task="", messages=[_user("some words", "m0")])
        assert scored[0].score == 0.0

    def test_empty_transcript_yields_no_scores(self) -> None:
        scorer = StubScorer()
        assert scorer.score(task="task", messages=[]) == []

    def test_name_is_stable(self) -> None:
        assert StubScorer().name == "stub"

    async def test_ascore_matches_score(self) -> None:
        scorer = StubScorer()
        messages = [_user("fix it", "m0")]
        assert await scorer.ascore(task="fix it", messages=messages) == scorer.score(
            task="fix it", messages=messages
        )
