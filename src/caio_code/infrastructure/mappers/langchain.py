"""Lossless mapping between domain messages and LangChain messages.

The domain never imports LangChain; this module is the only bridge. Two rules
make the mapping safe:

1. **Round trips lose nothing.** Ids, ``pinned``, tool calls and domain metadata
   travel inside ``additional_kwargs["caio_code"]``, so ``to_domain`` recovers
   the exact original even for fields LangChain has no slot for.
2. **Decisions are applied by index, in place.** ``apply_decision`` keeps the
   *same objects* for kept messages -- provider prompt caching depends on that
   identity -- substitutes in place, converts injected domain messages, and
   honours ``insert_at`` exactly like ``PolicyDecision.result`` does.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.policy.base import PipelineDecision, PolicyDecision

CAIO_CODE_KEY = "caio_code"
"""``additional_kwargs`` slot where the domain payload travels."""


def _content_text(content: Any) -> str:
    """LangChain content (str or blocks) as plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content) if content else ""


def _payload(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "pinned": message.pinned,
        "metadata": dict(message.metadata),
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ],
        "tool_call_id": message.tool_call_id,
        "name": message.name,
        "tokens": message.tokens,
    }


def _tool_call_args(arguments: str) -> dict[str, Any]:
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {"raw": arguments}
    return parsed if isinstance(parsed, dict) else {"raw": arguments}


def to_langchain(message: Message) -> BaseMessage:
    """Domain message as a LangChain message, with the full domain payload."""
    additional_kwargs = {CAIO_CODE_KEY: _payload(message)}
    if message.role is Role.SYSTEM:
        return SystemMessage(
            content=message.text, id=message.id, additional_kwargs=additional_kwargs
        )
    if message.role is Role.USER:
        return HumanMessage(
            content=message.text, id=message.id, additional_kwargs=additional_kwargs
        )
    if message.role is Role.ASSISTANT:
        return AIMessage(
            content=message.text,
            id=message.id,
            additional_kwargs=additional_kwargs,
            tool_calls=[
                {
                    "name": call.name,
                    "args": _tool_call_args(call.arguments),
                    "id": call.id,
                    "type": "tool_call",
                }
                for call in message.tool_calls
            ],
        )
    if message.role is Role.TOOL:
        return ToolMessage(
            content=message.text,
            id=message.id,
            additional_kwargs=additional_kwargs,
            tool_call_id=message.tool_call_id or "",
            name=message.name,
        )
    msg = f"unknown role {message.role!r}"
    raise ValueError(msg)


def _role_for(lc_message: BaseMessage) -> Role:
    if isinstance(lc_message, SystemMessage):
        return Role.SYSTEM
    if isinstance(lc_message, ToolMessage):
        return Role.TOOL
    if isinstance(lc_message, AIMessage):
        return Role.ASSISTANT
    if isinstance(lc_message, HumanMessage):
        return Role.USER
    by_type = {
        "system": Role.SYSTEM,
        "human": Role.USER,
        "ai": Role.ASSISTANT,
        "tool": Role.TOOL,
    }
    role = by_type.get(lc_message.type)
    if role is None:
        msg = f"cannot map LangChain message of type {lc_message.type!r} to a domain role"
        raise ValueError(msg)
    return role


def to_domain(lc_message: BaseMessage) -> Message:
    """LangChain message as a domain message, restoring the carried payload."""
    payload: dict[str, Any] = dict((lc_message.additional_kwargs or {}).get(CAIO_CODE_KEY) or {})
    role = _role_for(lc_message)

    tool_calls = tuple(
        ToolCall(id=item["id"], name=item["name"], arguments=item["arguments"])
        for item in payload.get("tool_calls", ())
    )
    if not tool_calls and isinstance(lc_message, AIMessage) and lc_message.tool_calls:
        tool_calls = tuple(
            ToolCall(
                id=call.get("id") or "",
                name=call.get("name") or "",
                arguments=json.dumps(
                    call.get("args") or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                ),
            )
            for call in lc_message.tool_calls
        )

    tool_call_id = payload.get("tool_call_id")
    if tool_call_id is None and isinstance(lc_message, ToolMessage):
        tool_call_id = lc_message.tool_call_id

    return Message(
        id=lc_message.id or payload.get("id") or "",
        role=role,
        text=_content_text(lc_message.content),
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        name=payload.get("name"),
        pinned=bool(payload.get("pinned", False)),
        tokens=payload.get("tokens"),
        metadata=dict(payload.get("metadata") or {}),
    )


def apply_decision(
    messages: Sequence[BaseMessage],
    decision: PolicyDecision,
) -> list[BaseMessage]:
    """Apply a domain decision BY INDEX to the original LangChain list.

    Kept messages are the same objects (identity preserved, so provider prompt
    caching keeps working), substitutions replace in place, injected messages
    are converted from the domain, and ``insert_at`` is honoured exactly as
    ``PolicyDecision.result`` does.
    """
    substitutions = {
        substitution.index: to_langchain(substitution.message)
        for substitution in decision.substitutions
    }
    kept = [
        substitutions.get(index, messages[index])
        for index in sorted(decision.kept_indices)
        if 0 <= index < len(messages)
    ]
    insert_at = max(0, min(decision.insert_at, len(kept)))
    injected = [to_langchain(message) for message in decision.injected]
    return [*kept[:insert_at], *injected, *kept[insert_at:]]


def apply_pipeline(
    messages: Sequence[BaseMessage],
    decision: PipelineDecision,
) -> list[BaseMessage]:
    """Fold every step decision over the list, each step indexing the previous."""
    current = list(messages)
    for step in decision.steps:
        current = apply_decision(current, step.decision)
    return current
