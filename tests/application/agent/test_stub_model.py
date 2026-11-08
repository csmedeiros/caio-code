"""The stub chat model: scripted, deterministic, usage in the OpenAI shape."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from caio_code.application.agent.stub_model import (
    StubChatModel,
    tool_turn,
)
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter


def _generate(model: StubChatModel, messages: list) -> AIMessage:
    result = model._generate(messages)
    return result.generations[0].message  # type: ignore[return-value]


def test_scripted_turns_are_consumed_in_order() -> None:
    model = StubChatModel(
        counter=CharProxyTokenCounter(),
        turns=(tool_turn("list_directory", {"path": "."}), "final answer"),
    )
    first = _generate(model, [HumanMessage(content="go")])
    assert first.tool_calls[0]["name"] == "list_directory"
    second = _generate(
        model,
        [HumanMessage(content="go"), first, ToolMessage(content="a.txt", tool_call_id="x")],
    )
    assert second.content == "final answer"
    assert not second.tool_calls


def test_usage_metadata_follows_the_openai_shape() -> None:
    model = StubChatModel(counter=CharProxyTokenCounter(), cached_input_fraction=0.5)
    message = _generate(model, [HumanMessage(content="abcd" * 10)])
    usage = message.usage_metadata
    assert usage is not None
    assert usage["input_tokens"] == 10
    assert usage["input_token_details"]["cache_read"] == 5
    token_usage = message.response_metadata["token_usage"]
    assert token_usage["prompt_tokens_details"]["cached_tokens"] == 5


def test_stub_is_reproducible() -> None:
    def transcript() -> list[str]:
        model = StubChatModel(counter=CharProxyTokenCounter())
        outputs = []
        messages: list = [HumanMessage(content="list things")]
        for _ in range(2):
            message = _generate(model, messages)
            outputs.append(str(message.content) + str(message.tool_calls))
            messages.append(message)
            if message.tool_calls:
                messages.append(
                    ToolMessage(content="a.txt\nb.py", tool_call_id=message.tool_calls[0]["id"])
                )
        return outputs

    assert transcript() == transcript()


def test_exhausted_script_adapts_to_last_tool_result() -> None:
    model = StubChatModel(counter=CharProxyTokenCounter(), turns=())
    message = _generate(
        model,
        [
            HumanMessage(content="go"),
            ToolMessage(content="a.txt\nb.py", tool_call_id="stub-call-0001"),
        ],
    )
    assert "last tool result" in str(message.content)
    assert "a.txt" in str(message.content)
