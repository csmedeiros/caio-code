"""Rendering a transcript as the plain text a summarizer reads.

Structurally the same rendering opencode feeds its compaction model: role
prefixes, tool calls with their arguments, tool results capped so a single
gigantic file dump cannot eat the summary budget.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from caio_code.domain.conversation.messages import Message, Role, Transcript

ATTACHMENT_PLACEHOLDER = "[attached: {mime}{name}]"


def _truncate(text: str, cap: int) -> str:
    if cap <= 0 or len(text) <= cap:
        return text
    return f"{text[:cap]}\n[truncated]"


def render_tool_arguments(arguments: str) -> str:
    """Tool arguments as compact JSON, or the raw string when it is not JSON."""
    if not arguments:
        return "{}"
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    return json.dumps(parsed, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def render_message(message: Message, *, tool_result_char_cap: int) -> str:
    """One message as text. Returns an empty string for content-free messages."""
    attachments = [
        ATTACHMENT_PLACEHOLDER.format(
            mime=item.get("mime", "application/octet-stream"),
            name=f": {item['name']}" if item.get("name") else "",
        )
        for item in message.metadata.get("attachments", ())
        if isinstance(item, dict)
    ]

    if message.role is Role.USER:
        parts = [f"[User]: {message.text}"] if message.text else []
        parts.extend(attachments)
        return "\n".join(parts)

    if message.role is Role.SYSTEM:
        return f"[System]: {message.text}" if message.text else ""

    if message.role is Role.TOOL:
        label = message.name or "tool"
        body = _truncate(message.text, tool_result_char_cap)
        if message.metadata.get("tool_error"):
            return f"[Tool error ({label})]: {body}"
        return f"[Tool result ({label})]: {body}"

    lines: list[str] = []
    if message.text:
        lines.append(f"[Assistant]: {message.text}")
    reasoning = message.metadata.get("reasoning")
    if isinstance(reasoning, str) and reasoning:
        lines.append(f"[Assistant reasoning]: {reasoning}")
    for call in message.tool_calls:
        lines.append(f"[Assistant tool call]: {call.name}({render_tool_arguments(call.arguments)})")
    lines.extend(attachments)
    return "\n".join(lines)


def render_transcript(
    transcript: Transcript | Iterable[Message],
    *,
    tool_result_char_cap: int,
) -> list[str]:
    """Each message rendered, dropping the ones that carry no text at all."""
    return [text for _, text in render_indexed(transcript, tool_result_char_cap=tool_result_char_cap)]


def render_indexed(
    transcript: Transcript | Iterable[Message],
    *,
    tool_result_char_cap: int,
) -> list[tuple[int, str]]:
    """Rendered chunks paired with their transcript index.

    Content-free messages are dropped, so the rendered sequence is shorter than
    the transcript. Keeping the index is what lets a caller translate a split in
    rendered space back into transcript positions without guessing.
    """
    messages: Sequence[Message] = (
        transcript.messages if isinstance(transcript, Transcript) else tuple(transcript)
    )
    pairs: list[tuple[int, str]] = []
    for index, message in enumerate(messages):
        chunk = render_message(message, tool_result_char_cap=tool_result_char_cap)
        if chunk:
            pairs.append((index, chunk))
    return pairs


def split_head_and_recent(
    rendered: Sequence[str],
    *,
    keep_tokens: int,
    token_counter,
) -> tuple[str, str]:
    """Walk backwards until the tail costs more than ``keep_tokens``.

    Returns ``(head, recent)``: the head is what gets summarized, the recent
    tail survives verbatim. A single message larger than the whole budget stays
    in the head, because dropping it would lose the newest fact of all.
    """
    head, recent, _ = split_indexed(rendered, keep_tokens=keep_tokens, token_counter=token_counter)
    return head, recent


def split_indexed(
    pairs: Sequence[tuple[int, str]],
    *,
    keep_tokens: int,
    token_counter,
) -> tuple[str, str, int]:
    """Same walk as :func:`split_head_and_recent`, over indexed chunks.

    Returns ``(head, recent, boundary)`` where ``boundary`` is the transcript
    index of the first message kept verbatim. When even the newest chunk is
    larger than ``keep_tokens``, nothing is kept verbatim and ``boundary`` is
    one past the last transcript index in ``pairs`` -- the caller reads that as
    "everything goes into the summary", never as "keep everything".
    """
    if not pairs:
        return "", "", 0
    accumulated = 0
    boundary = len(pairs)
    for position in range(len(pairs) - 1, -1, -1):
        cost = token_counter.count_text(pairs[position][1])
        if accumulated + cost > keep_tokens:
            break
        accumulated += cost
        boundary = position
    head = "\n".join(text for _, text in pairs[:boundary])
    recent = "\n".join(text for _, text in pairs[boundary:])
    first_kept = pairs[boundary][0] if boundary < len(pairs) else pairs[-1][0] + 1
    return head, recent, first_kept
