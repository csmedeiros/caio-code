"""Structure repair: keep the shaped transcript a provider will accept.

A retention policy decides *what* survives; it does not know that an assistant
message with ``tool_calls`` and its ``tool`` results are a pair the protocol
requires to travel together. Cut the head of a session and the tail starts with
an orphan tool result, or keeps a tool call whose answer was dropped - and an
OpenAI-compatible endpoint rejects the whole request with a 400. That is not a
provider quirk to work around, it is a property of the shaped context, so the
repair is a policy of its own and the last step of every pipeline.

Two rules, applied in one pass:

1. a tool result whose call is not among the kept assistant calls is dropped;
2. an assistant message whose calls lost their results keeps its text and loses
   those calls - and is dropped entirely when nothing of it remains.
"""

from __future__ import annotations

from caio_code.domain.conversation.messages import Message, Role, ToolCall, Transcript
from caio_code.domain.policy.base import (
    ContextPolicy,
    PolicyDecision,
    PolicyRequest,
    Removal,
    Substitution,
)

REPAIR_MARKER = "structure_repaired"


class StructureRepairPolicy(ContextPolicy):
    """Re-pairs tool calls and tool results after a retention policy ran."""

    def __init__(self, *, name: str = "structure_repair") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def plan(self, request: PolicyRequest) -> PolicyDecision:
        transcript = request.transcript
        costs = request.costs()
        tokens_before = sum(costs) + request.fixed_tokens

        kept_calls = _calls_by_id(transcript)
        removals: list[Removal] = []
        substitutions: list[Substitution] = []
        kept_indices: list[int] = []

        for index, message in enumerate(transcript):
            if message.role is Role.TOOL:
                call_id = message.tool_call_id or ""
                if call_id and call_id not in kept_calls:
                    removals.append(
                        Removal(index=index, reason=f"orphan tool result for call {call_id!r}")
                    )
                    continue
                kept_indices.append(index)
                continue

            if message.role is Role.ASSISTANT and message.tool_calls:
                resolved = tuple(
                    call for call in message.tool_calls if _has_result(transcript, call.id)
                )
                if len(resolved) == len(message.tool_calls):
                    kept_indices.append(index)
                    continue
                if not resolved and not message.text.strip():
                    removals.append(
                        Removal(
                            index=index,
                            reason=f"assistant message kept only unresolved calls: "
                            f"{[call.id for call in message.tool_calls]}",
                        )
                    )
                    continue
                substitutions.append(
                    Substitution(
                        index=index,
                        message=_with_calls(message, resolved),
                        reason=(
                            f"dropped {len(message.tool_calls) - len(resolved)} tool calls "
                            "whose results were removed"
                        ),
                    )
                )
                kept_indices.append(index)
                continue

            kept_indices.append(index)

        substituted = {item.index: item.message for item in substitutions}
        tokens_after = (
            sum(
                request.counter.count_message(substituted.get(index, transcript[index]))
                for index in kept_indices
            )
            + request.fixed_tokens
        )

        notes: list[str] = []
        if removals or substitutions:
            notes.append(
                f"repaired {len(removals)} orphan tool results and "
                f"{len(substitutions)} assistant messages with unresolved calls"
            )
        if tokens_after > request.budget.tokens:
            notes.append(
                f"repair could not bring the context under budget: {tokens_after} tokens "
                f"against {request.budget.tokens}"
            )

        return PolicyDecision(
            policy=self._name,
            kept_indices=tuple(kept_indices),
            counter=request.counter,
            removals=tuple(removals),
            substitutions=tuple(substitutions),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            budget_tokens=request.budget.tokens,
            notes=tuple(notes),
            detail={
                "orphan_tool_results": [item.index for item in removals],
                "stripped_assistant_messages": [item.index for item in substitutions],
                "messages_kept": len(kept_indices),
            },
        )


def _calls_by_id(transcript: Transcript) -> dict[str, ToolCall]:
    calls: dict[str, ToolCall] = {}
    for message in transcript:
        if message.role is Role.ASSISTANT:
            for call in message.tool_calls:
                calls[call.id] = call
    return calls


def _has_result(transcript: Transcript, call_id: str) -> bool:
    return any(
        message.role is Role.TOOL and message.tool_call_id == call_id for message in transcript
    )


def _with_calls(message: Message, calls: tuple[ToolCall, ...]) -> Message:
    repaired = Message(
        id=message.id,
        role=message.role,
        text=message.text,
        tool_calls=calls,
        tool_call_id=message.tool_call_id,
        name=message.name,
        pinned=message.pinned,
        metadata={**message.metadata, REPAIR_MARKER: True},
    )
    return repaired
