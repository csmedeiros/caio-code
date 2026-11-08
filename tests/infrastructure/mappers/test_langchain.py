"""Offline tests for the LangChain mappers."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, ToolCall, Transcript
from caio_code.domain.policy.base import (
    PolicyDecision,
    PolicyPipeline,
    PolicyRequest,
    Removal,
    Substitution,
)
from caio_code.domain.policy.sliding_window import SlidingWindowPolicy
from caio_code.infrastructure.mappers.langchain import (
    CAIO_CODE_KEY,
    apply_decision,
    apply_pipeline,
    to_domain,
    to_langchain,
)
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter


def _counter() -> CharProxyTokenCounter:
    return CharProxyTokenCounter()


def _message(
    message_id: str,
    role: Role,
    text: str,
    **kwargs,
) -> Message:
    return Message(id=message_id, role=role, text=text, **kwargs)


class TestRoundTrip:
    def test_user_message_round_trip(self) -> None:
        original = _message("u1", Role.USER, "do the thing", pinned=True, metadata={"k": "v"})
        assert to_domain(to_langchain(original)) == original

    def test_system_message_round_trip(self) -> None:
        original = _message("s1", Role.SYSTEM, "you are an agent")
        assert to_domain(to_langchain(original)) == original

    def test_tool_message_round_trip(self) -> None:
        original = _message(
            "t1", Role.TOOL, "file contents", tool_call_id="call-9", name="read_file"
        )
        restored = to_domain(to_langchain(original))
        assert restored == original
        assert restored.tool_call_id == "call-9"
        assert restored.name == "read_file"

    def test_assistant_with_tool_calls_round_trip(self) -> None:
        calls = (
            ToolCall(id="c1", name="ls", arguments='{"path": "src"}'),
            ToolCall(id="c2", name="read", arguments="not-json"),
        )
        original = _message("a1", Role.ASSISTANT, "let me look", tool_calls=calls, pinned=True)
        restored = to_domain(to_langchain(original))
        assert restored == original
        assert restored.tool_calls == calls

    def test_langchain_native_shapes_are_preserved(self) -> None:
        lc = to_langchain(_message("u1", Role.USER, "hi"))
        assert isinstance(lc, HumanMessage)
        assert lc.id == "u1"
        assert CAIO_CODE_KEY in lc.additional_kwargs
        payload = lc.additional_kwargs[CAIO_CODE_KEY]
        assert payload["pinned"] is False
        assert payload["id"] == "u1"

    def test_assistant_maps_to_ai_message_with_langchain_tool_calls(self) -> None:
        call = ToolCall(id="c1", name="ls", arguments='{"path": "src"}')
        lc = to_langchain(_message("a1", Role.ASSISTANT, "", tool_calls=(call,)))
        assert isinstance(lc, AIMessage)
        assert lc.tool_calls == [
            {"name": "ls", "args": {"path": "src"}, "id": "c1", "type": "tool_call"}
        ]

    def test_foreign_ai_message_without_payload_is_converted(self) -> None:
        lc = AIMessage(
            content="calling",
            id="x1",
            tool_calls=[{"name": "ls", "args": {"p": 1}, "id": "c9", "type": "tool_call"}],
        )
        restored = to_domain(lc)
        assert restored.id == "x1"
        assert restored.role is Role.ASSISTANT
        assert restored.tool_calls == (
            ToolCall(id="c9", name="ls", arguments=json.dumps({"p": 1}, separators=(",", ":"), sort_keys=True)),
        )

    def test_foreign_tool_message_uses_native_tool_call_id(self) -> None:
        restored = to_domain(ToolMessage(content="r", tool_call_id="c9", id="t9"))
        assert restored.role is Role.TOOL
        assert restored.tool_call_id == "c9"

    def test_block_content_is_flattened_to_text(self) -> None:
        lc = HumanMessage(content=[{"type": "text", "text": "a"}, "b"], id="u2")
        assert to_domain(lc).text == "ab"

    def test_empty_text_round_trip(self) -> None:
        original = _message("u3", Role.USER, "")
        assert to_domain(to_langchain(original)) == original


class TestApplyDecision:
    def _transcript(self) -> list[Message]:
        return [
            _message("m0", Role.SYSTEM, "system prompt", pinned=True),
            _message("m1", Role.USER, "task"),
            _message("m2", Role.ASSISTANT, "old answer"),
            _message("m3", Role.USER, "newer question"),
        ]

    def test_kept_messages_are_the_same_objects(self) -> None:
        domain = self._transcript()
        lc_messages = [to_langchain(message) for message in domain]
        decision = PolicyDecision(
            policy="sliding_window",
            kept_indices=(0, 2, 3),
            counter=_counter(),
            removals=(Removal(index=1, reason="outside the window"),),
        )
        result = apply_decision(lc_messages, decision)
        assert result == [lc_messages[0], lc_messages[2], lc_messages[3]]
        assert result[0] is lc_messages[0]
        assert result[1] is lc_messages[2]
        assert result[2] is lc_messages[3]

    def test_substitution_replaces_in_place(self) -> None:
        lc_messages = [to_langchain(message) for message in self._transcript()]
        replacement = _message("m2", Role.ASSISTANT, "[truncated]").with_text(
            "[truncated]", marker="tool_output"
        )
        decision = PolicyDecision(
            policy="tool_output",
            kept_indices=(0, 1, 2, 3),
            counter=_counter(),
            substitutions=(Substitution(index=2, message=replacement, reason="cap"),),
        )
        result = apply_decision(lc_messages, decision)
        assert result[2] is not lc_messages[2]
        assert to_domain(result[2]).text == "[truncated]"
        assert result[0] is lc_messages[0]

    def test_injected_message_honours_insert_at(self) -> None:
        lc_messages = [to_langchain(message) for message in self._transcript()]
        injected = _message("sum", Role.SYSTEM, "summary of the past")
        decision = PolicyDecision(
            policy="compaction",
            kept_indices=(0, 3),
            counter=_counter(),
            injected=(injected,),
            insert_at=1,
        )
        result = apply_decision(lc_messages, decision)
        assert [to_domain(item).id for item in result] == ["m0", "sum", "m3"]
        assert result[0] is lc_messages[0]
        assert result[2] is lc_messages[3]

    def test_insert_at_is_clamped(self) -> None:
        lc_messages = [to_langchain(message) for message in self._transcript()]
        injected = _message("sum", Role.SYSTEM, "s")
        decision = PolicyDecision(
            policy="compaction",
            kept_indices=(0,),
            counter=_counter(),
            injected=(injected,),
            insert_at=99,
        )
        result = apply_decision(lc_messages, decision)
        assert [to_domain(item).id for item in result] == ["m0", "sum"]

    def test_out_of_range_kept_indices_are_skipped(self) -> None:
        lc_messages = [to_langchain(message) for message in self._transcript()]
        decision = PolicyDecision(
            policy="test", kept_indices=(1, 42, -3), counter=_counter()
        )
        result = apply_decision(lc_messages, decision)
        assert result == [lc_messages[1]]

    def test_empty_decision_yields_empty_list(self) -> None:
        lc_messages = [to_langchain(message) for message in self._transcript()]
        decision = PolicyDecision(policy="test", kept_indices=(), counter=_counter())
        assert apply_decision(lc_messages, decision) == []

    def test_matches_domain_result_semantics(self) -> None:
        domain = self._transcript()
        lc_messages = [to_langchain(message) for message in domain]
        injected = _message("sum", Role.SYSTEM, "summary")
        decision = PolicyDecision(
            policy="compaction",
            kept_indices=(0, 3),
            counter=_counter(),
            injected=(injected,),
            insert_at=1,
        )
        expected = decision.result(Transcript.of(domain))
        restored = [to_domain(item) for item in apply_decision(lc_messages, decision)]
        assert restored == list(expected)


class TestApplyPipeline:
    def test_sliding_window_pipeline_preserves_tail_identity(self) -> None:
        counter = _counter()
        domain = [
            _message("m0", Role.SYSTEM, "sys" * 40, pinned=True),
            _message("m1", Role.USER, "old" * 40),
            _message("m2", Role.ASSISTANT, "mid" * 40),
            _message("m3", Role.USER, "new" * 40),
        ]
        lc_messages = [to_langchain(message) for message in domain]
        pipeline = PolicyPipeline("window", [SlidingWindowPolicy(keep_recent_messages=2)])
        request = PolicyRequest(
            transcript=Transcript.of(domain),
            budget=TokenBudget(tokens=80),
            counter=counter,
        )
        decision = pipeline.plan(request)
        result = apply_pipeline(lc_messages, decision)
        assert len(result) == len(decision.result())
        assert result[-1] is lc_messages[-1]
        assert result[-2] is lc_messages[-2]
        assert to_domain(result[0]).id == "m0"  # pinned survives
