"""Offline tests for transcript rendering and anchored-summary parsing."""

from __future__ import annotations

from caio_code.domain.conversation.messages import Message, Role, ToolCall, Transcript
from caio_code.domain.conversation.rendering import (
    render_indexed,
    render_message,
    render_transcript,
    split_indexed,
)
from caio_code.domain.conversation.summary import (
    PRIOR_SUMMARY_INSTRUCTION,
    empty_summary,
    parse_summary,
    summarizer_prompt,
)
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

COUNTER = CharProxyTokenCounter()
CAP = 2_000

WELL_FORMED = """\
## Objective
- finish the parser
## Important Details
- (none)
## Work State
### Completed
- lexer done
### Active
- parser in progress
### Blocked
- (none)
## Next Move
1. write the tests
## Relevant Files
- src/parser.py: the parser
"""


def _user(text: str, message_id: str = "u1") -> Message:
    return Message(id=message_id, role=Role.USER, text=text)


def test_render_message_formats_user_and_system_prefixes() -> None:
    assert render_message(_user("hello"), tool_result_char_cap=CAP) == "[User]: hello"
    system = Message(id="s1", role=Role.SYSTEM, text="rules")
    assert render_message(system, tool_result_char_cap=CAP) == "[System]: rules"


def test_render_message_formats_tool_results_and_errors() -> None:
    result = Message(id="t1", role=Role.TOOL, text="body", tool_call_id="c1", name="read")
    assert render_message(result, tool_result_char_cap=CAP) == "[Tool result (read)]: body"
    error = Message(
        id="t2",
        role=Role.TOOL,
        text="boom",
        tool_call_id="c1",
        name="shell",
        metadata={"tool_error": True},
    )
    assert render_message(error, tool_result_char_cap=CAP) == "[Tool error (shell)]: boom"


def test_render_message_formats_assistant_text_reasoning_and_tool_calls() -> None:
    message = Message(
        id="a1",
        role=Role.ASSISTANT,
        text="thinking aloud",
        tool_calls=(ToolCall(id="c1", name="grep", arguments='{"pattern": "x"}'),),
        metadata={"reasoning": "because"},
    )

    rendered = render_message(message, tool_result_char_cap=CAP)

    assert "[Assistant]: thinking aloud" in rendered
    assert "[Assistant reasoning]: because" in rendered
    assert '[Assistant tool call]: grep({"pattern":"x"})' in rendered


def test_tool_results_are_capped_with_a_truncated_marker() -> None:
    result = Message(
        id="t1", role=Role.TOOL, text="abcdefgh", tool_call_id="c1", name="read"
    )

    rendered = render_message(result, tool_result_char_cap=5)

    assert rendered == "[Tool result (read)]: abcde\n[truncated]"


def test_content_free_messages_render_empty_and_are_dropped() -> None:
    empty = _user("", "u-empty")
    transcript = Transcript.of([_user("a", "u1"), empty, _user("b", "u2")])

    assert render_message(empty, tool_result_char_cap=CAP) == ""
    assert render_transcript(transcript, tool_result_char_cap=CAP) == ["[User]: a", "[User]: b"]


def test_render_indexed_pairs_chunks_with_their_original_transcript_indices() -> None:
    transcript = Transcript.of([_user("a", "u1"), _user("", "u-empty"), _user("b", "u2")])

    pairs = render_indexed(transcript, tool_result_char_cap=CAP)

    assert [index for index, _ in pairs] == [0, 2]


def test_split_indexed_walks_backwards_and_returns_the_first_kept_transcript_index() -> None:
    chunk = "x" * 16  # 4 proxy tokens each
    pairs = [(0, chunk), (3, chunk), (7, chunk)]

    head, recent, first_kept = split_indexed(pairs, keep_tokens=8, token_counter=COUNTER)

    assert first_kept == 3
    assert head == chunk
    assert recent == f"{chunk}\n{chunk}"


def test_split_indexed_returns_one_past_the_last_index_when_the_newest_chunk_is_too_big() -> None:
    chunk = "x" * 16  # 4 proxy tokens
    pairs = [(0, chunk), (2, chunk)]

    head, recent, first_kept = split_indexed(pairs, keep_tokens=2, token_counter=COUNTER)

    assert first_kept == 3
    assert head == f"{chunk}\n{chunk}"
    assert recent == ""


def test_split_indexed_of_empty_pairs_is_empty() -> None:
    assert split_indexed([], keep_tokens=10, token_counter=COUNTER) == ("", "", 0)


def test_parse_summary_round_trips_a_well_formed_summary() -> None:
    summary = parse_summary(WELL_FORMED)

    assert summary.is_well_formed
    assert summary.missing_sections() == ()
    assert summary.text_of("Objective") == "- finish the parser"
    assert summary.section("Active") is not None
    rendered = summary.render()
    assert rendered.startswith("## Objective\n- finish the parser")
    assert "### Completed\n- lexer done" in rendered


def test_parse_summary_tolerates_unknown_headings() -> None:
    summary = parse_summary(f"{WELL_FORMED}## Notes\n- extra\n")

    assert summary.is_well_formed
    assert summary.text_of("Notes") == "- extra"


def test_parse_summary_reports_missing_sections() -> None:
    summary = parse_summary("## Objective\n- only one section\n")

    assert not summary.is_well_formed
    assert "important details" in summary.missing_sections()


def test_parse_summary_of_prose_without_headings_has_no_sections() -> None:
    summary = parse_summary("just prose, no headings at all")

    assert summary.sections == ()
    assert summary.raw == "just prose, no headings at all"


def test_empty_summary_is_well_formed() -> None:
    assert empty_summary().is_well_formed


def test_summarizer_prompt_differs_between_first_compaction_and_recompaction() -> None:
    first = summarizer_prompt(conversation=["hello"])
    again = summarizer_prompt(conversation=["hello"], previous_summary="## Objective\n- old")

    assert first != again
    assert "<prior-summary>" not in first
    assert "<prior-summary>" in again
    assert PRIOR_SUMMARY_INSTRUCTION in again
