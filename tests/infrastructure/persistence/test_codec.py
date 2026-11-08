"""Codec JSON: envelope versionado, round trip e erros que nomeiam o campo."""

from __future__ import annotations

import json
from typing import Any

import pytest

from caio_code.domain.conversation.messages import Message, Role, ToolCall, Transcript
from caio_code.domain.errors import StorageError
from caio_code.infrastructure.persistence.codec import (
    ENVELOPE_VERSION,
    envelope_session_id,
    message_from_dict,
    message_to_dict,
    transcript_from_dict,
    transcript_from_json,
    transcript_to_dict,
    transcript_to_json,
)

MESSAGE_KEYS = {
    "id",
    "role",
    "text",
    "tool_calls",
    "tool_call_id",
    "name",
    "pinned",
    "metadata",
}


def sample_transcript() -> Transcript:
    return Transcript.of(
        [
            Message(id="m1", role=Role.USER, text="task", pinned=True),
            Message(
                id="m2",
                role=Role.ASSISTANT,
                text="",
                tool_calls=(ToolCall(id="t1", name="read_file", arguments='{"path": "a"}'),),
            ),
            Message(
                id="m3",
                role=Role.TOOL,
                text="contents",
                tool_call_id="t1",
                name="read_file",
                metadata={"edits": ("tool_output_truncated",), "score": 1.5},
            ),
        ]
    )


def test_envelope_shape() -> None:
    envelope = transcript_to_dict(sample_transcript(), "session-1")
    assert set(envelope) == {"version", "session_id", "messages"}
    assert envelope["version"] == ENVELOPE_VERSION == 1
    assert envelope["session_id"] == "session-1"
    assert len(envelope["messages"]) == 3


def test_message_keys_are_exactly_the_contract() -> None:
    raw = message_to_dict(sample_transcript()[0])
    assert set(raw) == MESSAGE_KEYS


def test_round_trip_preserves_pinned_tool_calls_and_metadata() -> None:
    original = sample_transcript()
    restored = transcript_from_json(transcript_to_json(original, "s1"))
    assert len(restored) == len(original)
    assert restored[0].pinned is True
    assert restored[0].role is Role.USER
    assert restored[1].tool_calls == original[1].tool_calls
    assert isinstance(restored[1].tool_calls, tuple)
    assert restored[2].tool_call_id == "t1"
    assert restored[2].name == "read_file"
    assert restored[2].metadata["score"] == 1.5
    # tupla em metadata vira lista no JSON; tool_calls volta tupla (dataclass)
    assert restored[2].metadata["edits"] == ["tool_output_truncated"]


def test_tokens_are_not_serialized() -> None:
    message = Message(id="m", role=Role.USER, text="x", tokens=42)
    assert "tokens" not in message_to_dict(message)
    assert message_from_dict(message_to_dict(message), index=0).tokens is None


def test_unknown_envelope_version_raises() -> None:
    envelope = transcript_to_dict(sample_transcript(), "s1")
    envelope["version"] = 99
    with pytest.raises(StorageError, match="unknown envelope version: 99"):
        transcript_from_dict(envelope)


def test_missing_message_field_raises_naming_it() -> None:
    envelope = transcript_to_dict(sample_transcript(), "s1")
    del envelope["messages"][0]["pinned"]
    with pytest.raises(StorageError, match="message 0: missing field 'pinned'"):
        transcript_from_dict(envelope)


def test_unknown_role_raises_naming_the_value() -> None:
    raw = message_to_dict(sample_transcript()[0])
    raw["role"] = "robot"
    with pytest.raises(StorageError, match="field 'role' has unknown value 'robot'"):
        message_from_dict(raw, index=0)


def test_malformed_tool_call_raises_naming_the_field() -> None:
    raw = message_to_dict(sample_transcript()[1])
    raw["tool_calls"][0]["arguments"] = 7
    with pytest.raises(StorageError, match=r"tool_calls\[0\]: field 'arguments'"):
        message_from_dict(raw, index=1)


def test_non_object_message_raises() -> None:
    envelope: dict[str, Any] = {"version": 1, "session_id": "s", "messages": ["oops"]}
    with pytest.raises(StorageError, match="message 0: expected an object"):
        transcript_from_dict(envelope)


def test_empty_session_id_raises() -> None:
    with pytest.raises(StorageError, match="session_id must be a non-empty string"):
        transcript_to_dict(Transcript(), "")


def test_invalid_json_text_raises_naming_the_source() -> None:
    with pytest.raises(StorageError, match="disk: invalid JSON"):
        transcript_from_json("{not json", source="disk")


def test_envelope_session_id_helper() -> None:
    envelope = transcript_to_dict(sample_transcript(), "s42")
    assert envelope_session_id(envelope) == "s42"


def test_envelope_survives_plain_json_round_trip() -> None:
    envelope = json.loads(json.dumps(transcript_to_dict(sample_transcript(), "s1")))
    restored = transcript_from_dict(envelope)
    assert len(restored) == 3
    assert restored[0].text == "task"
