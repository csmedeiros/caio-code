"""Offline tests for the structure-repair policy: tool call/result re-pairing."""

from __future__ import annotations

from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, ToolCall, Transcript
from caio_code.domain.policy.base import PolicyRequest
from caio_code.domain.policy.structure_repair import REPAIR_MARKER, StructureRepairPolicy
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

COUNTER = CharProxyTokenCounter()
BUDGET = TokenBudget(10_000)


def _request(transcript: Transcript) -> PolicyRequest:
    return PolicyRequest(transcript=transcript, budget=BUDGET, counter=COUNTER)


def _user(text: str, message_id: str = "u1", *, pinned: bool = False) -> Message:
    return Message(id=message_id, role=Role.USER, text=text, pinned=pinned)


def _assistant(
    text: str,
    calls: tuple[ToolCall, ...] = (),
    message_id: str = "a1",
) -> Message:
    return Message(id=message_id, role=Role.ASSISTANT, text=text, tool_calls=calls)


def _tool(call_id: str, message_id: str = "t1", text: str = "result") -> Message:
    return Message(
        id=message_id, role=Role.TOOL, text=text, tool_call_id=call_id, name="read"
    )


def test_orphan_tool_result_is_dropped() -> None:
    transcript = Transcript.of([_user("hi"), _tool("call-missing")])

    decision = StructureRepairPolicy().plan(_request(transcript))

    assert decision.kept_indices == (0,)
    assert [removal.index for removal in decision.removals] == [1]
    assert "orphan" in decision.removals[0].reason
    assert len(decision.result(transcript)) == 1


def test_assistant_keeps_text_and_resolved_call_and_loses_only_unresolved() -> None:
    resolved = ToolCall(id="c1", name="read", arguments="{}")
    unresolved = ToolCall(id="c2", name="grep", arguments="{}")
    assistant = _assistant("working on it", calls=(resolved, unresolved))
    transcript = Transcript.of([assistant, _tool("c1")])

    decision = StructureRepairPolicy().plan(_request(transcript))

    assert decision.kept_indices == (0, 1)
    assert len(decision.substitutions) == 1
    repaired = decision.substitutions[0].message
    assert repaired.text == "working on it"
    assert repaired.tool_calls == (resolved,)
    assert repaired.metadata[REPAIR_MARKER] is True
    assert decision.result(transcript)[0].tool_calls == (resolved,)


def test_assistant_whose_only_content_was_unresolved_calls_is_dropped() -> None:
    assistant = _assistant("", calls=(ToolCall(id="c1", name="read", arguments="{}"),))
    transcript = Transcript.of([_user("hi"), assistant])

    decision = StructureRepairPolicy().plan(_request(transcript))

    assert decision.kept_indices == (0,)
    assert [removal.index for removal in decision.removals] == [1]
    assert "unresolved calls" in decision.removals[0].reason


def test_transcript_without_tool_traffic_is_returned_unchanged() -> None:
    messages = [_user("hi", "u1"), _assistant("hello", message_id="a1"), _user("bye", "u2")]
    transcript = Transcript.of(messages)

    decision = StructureRepairPolicy().plan(_request(transcript))

    assert decision.kept_indices == (0, 1, 2)
    assert decision.removals == ()
    assert decision.substitutions == ()
    result = decision.result(transcript)
    assert all(kept is original for kept, original in zip(result, messages, strict=True))


def test_pinned_messages_survive_repair() -> None:
    pinned = _user("the task", "u0", pinned=True)
    transcript = Transcript.of([pinned, _tool("call-missing"), _user("more", "u2")])

    decision = StructureRepairPolicy().plan(_request(transcript))

    assert decision.kept_indices == (0, 2)
    assert decision.result(transcript)[0] is pinned


def test_decision_reports_token_counts_and_touched_indices() -> None:
    resolved = ToolCall(id="c1", name="read", arguments="{}")
    unresolved = ToolCall(id="c2", name="grep", arguments="{}")
    transcript = Transcript.of(
        [
            _assistant("text", calls=(resolved, unresolved), message_id="a1"),
            _tool("c1"),
            _tool("call-missing", message_id="t2"),
        ]
    )

    decision = StructureRepairPolicy().plan(_request(transcript))

    assert decision.tokens_before == COUNTER.count_transcript(transcript)
    assert decision.tokens_after == COUNTER.count_transcript(decision.result(transcript))
    assert decision.detail["orphan_tool_results"] == [2]
    assert decision.detail["stripped_assistant_messages"] == [0]


def test_empty_transcript_is_a_noop() -> None:
    decision = StructureRepairPolicy().plan(_request(Transcript()))

    assert decision.kept_indices == ()
    assert decision.removals == ()
    assert decision.substitutions == ()
    assert decision.tokens_before == 0
    assert decision.tokens_after == 0
    assert len(decision.result(Transcript())) == 0
