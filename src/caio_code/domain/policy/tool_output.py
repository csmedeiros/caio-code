"""Tool-output truncation: cap a tool result before it enters the context.

Orthogonal to the other strategies, which is why the experiment also runs it in
combination with them: it shrinks the *content* of individual messages instead
of choosing *which* messages survive. The cut keeps head and tail, because the
first lines of a file give its shape and the last lines carry the error that
just happened. Nothing is dropped silently: the marker states what was removed.
"""

from __future__ import annotations

from dataclasses import dataclass

from caio_code.domain.conversation.messages import Message
from caio_code.domain.policy.base import ContextPolicy, PolicyDecision, PolicyRequest, Substitution

MARKER_TEMPLATE = "... output truncated; {lines} of {total_lines} lines and {bytes} of {total_bytes} bytes omitted ..."


@dataclass(frozen=True, slots=True)
class TruncationLimits:
    """Ceilings for one tool result."""

    max_lines: int = 2_000
    max_bytes: int = 51_200

    def __post_init__(self) -> None:
        if self.max_lines <= 0:
            msg = f"max_lines must be positive, got {self.max_lines}"
            raise ValueError(msg)
        if self.max_bytes <= 0:
            msg = f"max_bytes must be positive, got {self.max_bytes}"
            raise ValueError(msg)


def truncate_text(text: str, limits: TruncationLimits) -> tuple[str, bool]:
    """Apply the line and byte ceilings, keeping head and tail.

    Returns the text and whether anything was removed. Line splitting comes
    first because a single enormous line still has to be cut by bytes.
    """
    if not text:
        return text, False

    total_lines = text.count("\n") + 1
    total_bytes = len(text.encode("utf-8"))
    lines = text.split("\n")

    kept_lines = lines
    line_cut = False
    if total_lines > limits.max_lines:
        head_lines = (limits.max_lines + 1) // 2
        tail_lines = limits.max_lines // 2
        kept_lines = [*lines[:head_lines], *(lines[-tail_lines:] if tail_lines else [])]
        line_cut = True

    joined = "\n".join(kept_lines)
    byte_cut = False
    if len(joined.encode("utf-8")) > limits.max_bytes:
        head_bytes = (limits.max_bytes + 1) // 2
        tail_bytes = limits.max_bytes // 2
        encoded = joined.encode("utf-8")
        head = encoded[:head_bytes].decode("utf-8", errors="ignore")
        tail = encoded[-tail_bytes:].decode("utf-8", errors="ignore") if tail_bytes else ""
        joined = f"{head}\n{tail}" if tail else head
        byte_cut = True

    if not line_cut and not byte_cut:
        return text, False

    omitted_lines = max(0, total_lines - (joined.count("\n") + 1))
    omitted_bytes = max(0, total_bytes - len(joined.encode("utf-8")))
    marker = MARKER_TEMPLATE.format(
        lines=omitted_lines,
        total_lines=total_lines,
        bytes=omitted_bytes,
        total_bytes=total_bytes,
    )
    return f"{joined}\n{marker}", True


class ToolOutputTruncationPolicy(ContextPolicy):
    """Rewrite oversized tool results in place; drop nothing."""

    def __init__(
        self,
        *,
        limits: TruncationLimits | None = None,
        max_lines: int = 2_000,
        max_bytes: int = 51_200,
        truncate_all_roles: bool = False,
        name: str = "tool_output_truncation",
    ) -> None:
        self._limits = limits or TruncationLimits(max_lines=max_lines, max_bytes=max_bytes)
        self._truncate_all_roles = truncate_all_roles
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def limits(self) -> TruncationLimits:
        return self._limits

    def plan(self, request: PolicyRequest) -> PolicyDecision:
        transcript = request.transcript
        costs = request.costs()
        tokens_before = sum(costs) + request.fixed_tokens

        substitutions: list[Substitution] = []
        truncated_indices: list[int] = []
        bytes_saved = 0

        for index, message in enumerate(transcript):
            if not self._is_candidate(message):
                continue
            new_text, changed = truncate_text(message.text, self._limits)
            if not changed:
                continue
            bytes_saved += len(message.text.encode("utf-8")) - len(new_text.encode("utf-8"))
            truncated_indices.append(index)
            substitutions.append(
                Substitution(
                    index=index,
                    message=message.with_text(new_text, marker="tool_output_truncated"),
                    reason=f"tool output above {self._limits.max_bytes} bytes",
                )
            )

        substituted = {item.index: item.message for item in substitutions}
        tokens_after = (
            sum(
                request.counter.count_message(substituted.get(index, message))
                for index, message in enumerate(transcript)
            )
            + request.fixed_tokens
        )

        notes: list[str] = []
        if tokens_after > request.budget.tokens:
            notes.append(
                f"truncation alone does not fit the budget: {tokens_after} tokens against "
                f"{request.budget.tokens}; combine it with a retention policy"
            )

        return PolicyDecision(
            policy=self._name,
            kept_indices=tuple(range(len(transcript))),
            counter=request.counter,
            substitutions=tuple(substitutions),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            budget_tokens=request.budget.tokens,
            notes=tuple(notes),
            detail={
                "truncated_messages": truncated_indices,
                "bytes_saved": bytes_saved,
                "limits": {
                    "max_lines": self._limits.max_lines,
                    "max_bytes": self._limits.max_bytes,
                },
            },
        )

    def _is_candidate(self, message: Message) -> bool:
        if self._truncate_all_roles:
            return bool(message.text)
        return message.is_tool_result() and bool(message.text)
