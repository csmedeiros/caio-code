"""Offline tests for the policy pipeline and the individual shaping policies."""

from __future__ import annotations

import pytest

from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.policy.base import PolicyPipeline, PolicyRequest
from caio_code.domain.policy.full_history import FullHistoryPolicy
from caio_code.domain.policy.message_selection import MessageSelectionPolicy
from caio_code.domain.policy.sliding_window import SlidingWindowPolicy
from caio_code.domain.policy.tool_output import (
    ToolOutputTruncationPolicy,
    TruncationLimits,
    truncate_text,
)
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

COUNTER = CharProxyTokenCounter()
BLOCK = "x" * 40  # exactly 10 proxy tokens


def _message(message_id: str, text: str = BLOCK, *, pinned: bool = False) -> Message:
    return Message(id=message_id, role=Role.USER, text=text, pinned=pinned)


def _tool_result(message_id: str, text: str) -> Message:
    return Message(id=message_id, role=Role.TOOL, text=text, tool_call_id="c1", name="read")


def _request(transcript: Transcript, budget: TokenBudget, **kwargs: object) -> PolicyRequest:
    return PolicyRequest(transcript=transcript, budget=budget, counter=COUNTER, **kwargs)  # type: ignore[arg-type]


def test_pipeline_threads_the_transcript_from_truncation_into_the_window() -> None:
    huge = "\n".join(f"line {i}" for i in range(200))
    transcript = Transcript.of(
        [_tool_result("t1", huge), _message("u1"), _message("u2"), _message("u3")]
    )
    pipeline = PolicyPipeline(
        "truncate_then_window",
        [
            ToolOutputTruncationPolicy(limits=TruncationLimits(max_lines=4, max_bytes=60)),
            SlidingWindowPolicy(keep_recent_messages=1),
        ],
    )

    decision = pipeline.plan(_request(transcript, TokenBudget(40)))

    truncation, window = decision.steps
    assert truncation.decision.tokens_after < truncation.decision.tokens_before
    # The window step saw the truncated transcript, not the original one.
    assert window.decision.tokens_before == truncation.decision.tokens_after


def test_pipeline_steps_carry_own_numbers_and_last_transcript_is_the_result() -> None:
    huge = "\n".join(f"line {i}" for i in range(200))
    transcript = Transcript.of(
        [_tool_result("t1", huge), _message("u1"), _message("u2"), _message("u3")]
    )
    pipeline = PolicyPipeline(
        "truncate_then_window",
        [
            ToolOutputTruncationPolicy(limits=TruncationLimits(max_lines=4, max_bytes=60)),
            SlidingWindowPolicy(keep_recent_messages=1),
        ],
    )

    decision = pipeline.plan(_request(transcript, TokenBudget(40)))

    assert decision.steps[0].decision.tokens_after != decision.steps[1].decision.tokens_after
    assert decision.result() == decision.steps[-1].transcript
    assert decision.tokens_after == COUNTER.count_transcript(decision.result())


def test_baseline_policy_reports_overflow_instead_of_hiding_it() -> None:
    transcript = Transcript.of([_message("u1"), _message("u2")])

    decision = FullHistoryPolicy().plan(_request(transcript, TokenBudget(5)))

    assert decision.overflow_tokens == 15
    assert decision.overflowed
    assert decision.notes


def test_tool_truncation_policy_reports_overflow_instead_of_hiding_it() -> None:
    transcript = Transcript.of([_message("u1"), _message("u2")])

    decision = ToolOutputTruncationPolicy().plan(_request(transcript, TokenBudget(5)))

    assert decision.overflow_tokens > 0
    assert decision.overflowed


def test_sliding_window_keeps_a_contiguous_suffix_plus_pinned() -> None:
    transcript = Transcript.of(
        [
            _message("task", pinned=True),
            _message("u1"),
            _message("u2"),
            _message("u3"),
            _message("u4"),
            _message("u5"),
        ]
    )

    decision = SlidingWindowPolicy(keep_recent_messages=2).plan(
        _request(transcript, TokenBudget(25))
    )

    assert decision.kept_indices == (0, 4, 5)
    assert [removal.index for removal in decision.removals] == [1, 2, 3]
    assert all("sliding window" in removal.reason for removal in decision.removals)


def test_message_selection_with_scores_keeps_the_highest_scoring_messages() -> None:
    transcript = Transcript.of([_message(f"u{i}") for i in range(5)])

    decision = MessageSelectionPolicy(keep_recent_messages=0, top_k_floor=0).plan(
        _request(transcript, TokenBudget(30), scores=[0.9, 0.1, 0.8, 0.2, 0.5])
    )

    assert decision.kept_indices == (0, 2, 4)


def test_message_selection_without_scores_degrades_to_recency_with_a_note() -> None:
    transcript = Transcript.of([_message(f"u{i}") for i in range(5)])

    decision = MessageSelectionPolicy(keep_recent_messages=1).plan(
        _request(transcript, TokenBudget(30))
    )

    assert decision.kept_indices == (2, 3, 4)
    assert "no scores supplied: selection degraded to recency" in decision.notes
    assert decision.detail["scorer"] == "recency"


def test_short_score_sequence_raises_value_error_naming_both_counts() -> None:
    transcript = Transcript.of([_message(f"u{i}") for i in range(3)])

    with pytest.raises(ValueError, match=r"scores has 2 entries for 3 messages"):
        _request(transcript, TokenBudget(100), scores=[0.1, 0.2])


def test_duplicated_score_sequence_of_wrong_length_raises_value_error() -> None:
    transcript = Transcript.of([_message(f"u{i}") for i in range(3)])

    with pytest.raises(ValueError, match=r"scores has 2 entries for 3 messages"):
        _request(transcript, TokenBudget(100), scores=[0.5, 0.5])


def test_tool_output_truncation_keeps_head_and_tail_with_an_explicit_marker() -> None:
    text = "\n".join(f"line{i}" for i in range(10))

    truncated, changed = truncate_text(text, TruncationLimits(max_lines=4, max_bytes=10_000))

    assert changed
    lines = truncated.splitlines()
    assert lines[0] == "line0"
    assert lines[1] == "line1"
    assert lines[2] == "line8"
    assert lines[3] == "line9"
    assert "6 of 10 lines" in lines[4]
    assert "36 of 59 bytes omitted" in lines[4]


def test_tool_output_truncation_policy_substitutes_in_place_and_drops_nothing() -> None:
    huge = "\n".join(f"line{i}" for i in range(100))
    transcript = Transcript.of([_message("u1"), _tool_result("t1", huge)])

    decision = ToolOutputTruncationPolicy(
        limits=TruncationLimits(max_lines=4, max_bytes=10_000)
    ).plan(_request(transcript, TokenBudget(10_000)))

    assert decision.kept_indices == (0, 1)
    assert decision.removals == ()
    assert len(decision.substitutions) == 1
    replacement = decision.substitutions[0].message
    assert replacement.text.startswith("line0")
    assert "line99" in replacement.text
    assert "omitted" in replacement.text
    assert decision.tokens_after < decision.tokens_before
