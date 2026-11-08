"""JSON codec for transcripts: the envelope another adapter may rely on.

Envelope::

    {"version": 1, "session_id": "<str>", "messages": [<message>, ...]}

Message keys::

    id, role, text, tool_calls [{"id", "name", "arguments"}],
    tool_call_id, name, pinned, metadata

``tokens`` is a cache and is deliberately not serialized. ``metadata`` values
that are tuples are written as JSON lists; only ``tool_calls`` is restored as a
tuple, because that is what the dataclass expects. Unknown version or a
malformed message raises ``StorageError`` naming the offending field.
"""

from __future__ import annotations

import json
from typing import Any

from caio_code.domain.conversation.messages import Message, Role, ToolCall, Transcript
from caio_code.domain.errors import StorageError

ENVELOPE_VERSION = 1

_MESSAGE_FIELDS = (
    "id",
    "role",
    "text",
    "tool_calls",
    "tool_call_id",
    "name",
    "pinned",
    "metadata",
)


def _to_jsonable(value: Any) -> Any:
    """Tuples become lists, recursively; anything else passes through json."""
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def message_to_dict(message: Message) -> dict[str, Any]:
    """Serialize one message with the canonical key set."""
    return {
        "id": message.id,
        "role": str(message.role.value),
        "text": message.text,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
        "name": message.name,
        "pinned": message.pinned,
        "metadata": _to_jsonable(message.metadata),
    }


def _require_str(raw: dict[str, Any], field: str, where: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str):
        msg = f"{where}: field {field!r} must be a string, got {value!r}"
        raise StorageError(msg)
    return value


def message_from_dict(raw: Any, *, index: int | None = None) -> Message:
    """Rebuild a message; raises ``StorageError`` naming the bad field."""
    where = f"message {index}" if index is not None else "message"
    if not isinstance(raw, dict):
        msg = f"{where}: expected an object, got {type(raw).__name__}"
        raise StorageError(msg)
    for field in _MESSAGE_FIELDS:
        if field not in raw:
            msg = f"{where}: missing field {field!r}"
            raise StorageError(msg)

    role_raw = raw["role"]
    try:
        role = Role(role_raw)
    except ValueError as exc:
        msg = f"{where}: field 'role' has unknown value {role_raw!r}"
        raise StorageError(msg) from exc

    text = raw["text"]
    if not isinstance(text, str):
        msg = f"{where}: field 'text' must be a string, got {text!r}"
        raise StorageError(msg)

    calls_raw = raw["tool_calls"]
    if not isinstance(calls_raw, list):
        msg = f"{where}: field 'tool_calls' must be a list, got {calls_raw!r}"
        raise StorageError(msg)
    tool_calls: list[ToolCall] = []
    for position, call_raw in enumerate(calls_raw):
        call_where = f"{where}, tool_calls[{position}]"
        if not isinstance(call_raw, dict):
            msg = f"{call_where}: expected an object, got {type(call_raw).__name__}"
            raise StorageError(msg)
        tool_calls.append(
            ToolCall(
                id=_require_str(call_raw, "id", call_where),
                name=_require_str(call_raw, "name", call_where),
                arguments=_require_str(call_raw, "arguments", call_where),
            )
        )

    tool_call_id = raw["tool_call_id"]
    if tool_call_id is not None and not isinstance(tool_call_id, str):
        msg = f"{where}: field 'tool_call_id' must be a string or null, got {tool_call_id!r}"
        raise StorageError(msg)

    name = raw["name"]
    if name is not None and not isinstance(name, str):
        msg = f"{where}: field 'name' must be a string or null, got {name!r}"
        raise StorageError(msg)

    pinned = raw["pinned"]
    if not isinstance(pinned, bool):
        msg = f"{where}: field 'pinned' must be a boolean, got {pinned!r}"
        raise StorageError(msg)

    metadata = raw["metadata"]
    if not isinstance(metadata, dict):
        msg = f"{where}: field 'metadata' must be an object, got {metadata!r}"
        raise StorageError(msg)

    return Message(
        id=_require_str(raw, "id", where),
        role=role,
        text=text,
        tool_calls=tuple(tool_calls),
        tool_call_id=tool_call_id,
        name=name,
        pinned=pinned,
        tokens=None,
        metadata=dict(metadata),
    )


def transcript_to_dict(transcript: Transcript, session_id: str) -> dict[str, Any]:
    """Serialize a transcript into the versioned envelope."""
    if not isinstance(session_id, str) or not session_id:
        msg = f"session_id must be a non-empty string, got {session_id!r}"
        raise StorageError(msg)
    return {
        "version": ENVELOPE_VERSION,
        "session_id": session_id,
        "messages": [message_to_dict(message) for message in transcript.messages],
    }


def _check_envelope(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        msg = f"transcript envelope must be an object, got {type(raw).__name__}"
        raise StorageError(msg)
    version = raw.get("version")
    if version != ENVELOPE_VERSION:
        msg = f"unknown envelope version: {version!r} (expected {ENVELOPE_VERSION})"
        raise StorageError(msg)
    if not isinstance(raw.get("session_id"), str):
        msg = f"envelope field 'session_id' must be a string, got {raw.get('session_id')!r}"
        raise StorageError(msg)
    messages = raw.get("messages")
    if not isinstance(messages, list):
        msg = f"envelope field 'messages' must be a list, got {messages!r}"
        raise StorageError(msg)
    return raw


def envelope_session_id(raw: dict[str, Any]) -> str:
    """The ``session_id`` of a validated envelope."""
    _check_envelope(raw)
    session_id: str = raw["session_id"]
    return session_id


def transcript_from_dict(raw: Any) -> Transcript:
    """Rebuild a transcript from the envelope; validates version and fields."""
    envelope = _check_envelope(raw)
    return Transcript.of(
        message_from_dict(message, index=index)
        for index, message in enumerate(envelope["messages"])
    )


def transcript_to_json(transcript: Transcript, session_id: str) -> str:
    """Envelope as a single JSON line-safe string."""
    return json.dumps(transcript_to_dict(transcript, session_id), ensure_ascii=False)


def transcript_from_json(text: str, *, source: str = "<transcript>") -> Transcript:
    """Parse the envelope from JSON text; corrupt input names the source."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"{source}: invalid JSON: {exc}"
        raise StorageError(msg) from exc
    return transcript_from_dict(raw)


__all__ = [
    "ENVELOPE_VERSION",
    "envelope_session_id",
    "message_from_dict",
    "message_to_dict",
    "transcript_from_dict",
    "transcript_from_json",
    "transcript_to_dict",
    "transcript_to_json",
]
