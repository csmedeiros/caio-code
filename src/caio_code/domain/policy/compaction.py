"""Task-directed compaction: fold the head of the transcript into a summary.

The planner is pure. It decides *what* gets summarized (everything older than
the verbatim tail) and *what the summarizer is asked*, and it returns a decision
whose injected message is a placeholder until the application layer fills it
with the model's answer. That split is what keeps an LLM call out of the domain
and lets the planning be tested without one.
"""

from __future__ import annotations

from collections.abc import Sequence

from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.conversation.rendering import render_indexed
from caio_code.domain.conversation.summary import (
    SUMMARY_MESSAGE_PREFIX,
    AnchoredSummary,
    summarizer_prompt,
)
from caio_code.domain.policy.base import ContextPolicy, PolicyDecision, PolicyRequest, Removal

SUMMARY_PLACEHOLDER = "[summary pending]"
HEAD_BOUNDARY_NOTE = "head summarized"
HEAD_OMITTED_MARKER = "[earlier context omitted: it exceeded the summarizer head cap]"


class CompactionPlanner(ContextPolicy):
    """Plans a compaction: head -> summary, recent tail kept verbatim.

    ``keep_tokens`` is a *ceiling* on the verbatim tail, not a promise: the tail
    the planner actually keeps is the smaller of that ceiling and what is left of
    the window once the fixed cost and the summary are paid for.
    """

    def __init__(
        self,
        *,
        keep_tokens: int = 8_000,
        summary_allowance_tokens: int = 0,
        tool_result_char_cap: int = 2_000,
        head_char_cap: int = 0,
        summary_message_id: str = "compaction:summary",
        name: str = "anchored_compaction",
    ) -> None:
        if keep_tokens < 0:
            msg = f"keep_tokens must be non-negative, got {keep_tokens}"
            raise ValueError(msg)
        if summary_allowance_tokens < 0:
            msg = (
                "summary_allowance_tokens must be non-negative, got "
                f"{summary_allowance_tokens}"
            )
            raise ValueError(msg)
        if tool_result_char_cap <= 0:
            msg = f"tool_result_char_cap must be positive, got {tool_result_char_cap}"
            raise ValueError(msg)
        if head_char_cap < 0:
            msg = f"head_char_cap must be non-negative, got {head_char_cap}"
            raise ValueError(msg)
        self._keep_tokens = keep_tokens
        self._summary_allowance = summary_allowance_tokens
        self._cap = tool_result_char_cap
        self._head_cap = head_char_cap
        self._summary_id = summary_message_id
        self._name = name

    def _tail_budget(self, request: PolicyRequest) -> int:
        """Tokens the verbatim tail may cost.

        The summary that replaces the head is sent too, so it is paid for out of
        the same window: a tail sized to the whole window with a summary stacked
        on top overflows by construction, however well the summarizer behaves.
        Reserving the allowance here is what makes "fits the window" a property
        of the policy instead of a hope about the model's output length.
        """
        available = (
            request.budget.tokens - request.fixed_tokens - self._summary_allowance
        )
        return max(0, min(self._keep_tokens, available))

    @property
    def name(self) -> str:
        return self._name

    def plan(self, request: PolicyRequest) -> PolicyDecision:
        transcript = request.transcript
        costs = request.costs()
        tokens_before = sum(costs) + request.fixed_tokens

        tail_budget = self._tail_budget(request)
        boundary = tail_boundary(costs, keep_tokens=tail_budget)
        pairs = render_indexed(transcript, tool_result_char_cap=self._cap)
        head = "\n".join(text for index, text in pairs if index < boundary)
        recent = "\n".join(text for index, text in pairs if index >= boundary)

        pinned = set(transcript.pinned_indices())
        if not head.strip() or boundary <= 0:
            # Nothing old enough to fold: the transcript already fits the tail budget.
            return PolicyDecision(
                policy=self._name,
                kept_indices=tuple(range(len(transcript))),
                counter=request.counter,
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                budget_tokens=request.budget.tokens,
                notes=("nothing to compact: transcript fits the verbatim tail",),
                detail={"compacted": False, "head_chars": 0, "recent_chars": len(recent)},
            )

        kept = sorted(pinned | set(range(boundary, len(transcript))))
        kept_set = set(kept)
        removals = tuple(
            Removal(index=index, reason=HEAD_BOUNDARY_NOTE)
            for index in range(len(transcript))
            if index not in kept_set
        )
        # The summary replaces the head, so it goes right after the pinned
        # messages that precede the boundary and before the verbatim tail.
        insert_at = sum(1 for index in kept if index < boundary)

        head_for_prompt, head_omitted_chars = cap_head(head, self._head_cap)
        previous = request.previous_summary
        prompt = summarizer_prompt(
            conversation=[previous.render() if previous else "", head_for_prompt],
            previous_summary=previous.render() if previous else None,
        )
        summary_message = Message(
            id=self._summary_id,
            # The summary reads as something the agent itself produced, not as
            # an instruction from the user: it enters the transcript as an
            # assistant message (Chapter 4 methodology).
            role=Role.ASSISTANT,
            text=f"{SUMMARY_MESSAGE_PREFIX}\n{SUMMARY_PLACEHOLDER}",
            pinned=True,
            metadata={"compaction_prompt": prompt, "compaction_head_chars": len(head)},
        )

        # Cost after compaction: summary placeholder + pinned head + tail. The
        # real summary cost is re-measured by the caller once the model answers.
        provisional = Transcript.of(
            (
                *(transcript[index] for index in kept if index < boundary),
                summary_message,
                *(transcript[index] for index in kept if index >= boundary),
            )
        )
        tokens_after = request.counter.count_transcript(provisional) + request.fixed_tokens

        notes: list[str] = []
        if tokens_after > request.budget.tokens:
            notes.append(
                f"compaction floor: summary plus verbatim tail cost {tokens_after} tokens "
                f"against a budget of {request.budget.tokens}; reduce keep_tokens"
            )

        return PolicyDecision(
            policy=self._name,
            kept_indices=tuple(kept),
            counter=request.counter,
            removals=removals,
            injected=(summary_message,),
            insert_at=insert_at,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            budget_tokens=request.budget.tokens,
            notes=tuple(notes),
            detail={
                "compacted": True,
                "boundary": boundary,
                "head_chars": len(head),
                "head_chars_sent": len(head_for_prompt),
                "head_chars_omitted": head_omitted_chars,
                "recent_chars": len(recent),
                "prompt_chars": len(prompt),
                "messages_kept": len(kept),
            },
        )


def summary_message_from(
    decision: PolicyDecision,
    summary: AnchoredSummary,
    *,
    message_id: str = "compaction:summary",
) -> Message:
    """Replace the placeholder with the model's anchored summary.

    The replacement keeps the planner's role contract: the summary is an
    assistant message, because it stands for what the agent condensed from its
    own earlier context.
    """
    return Message(
        id=message_id,
        role=Role.ASSISTANT,
        text=f"{SUMMARY_MESSAGE_PREFIX}\n{summary.render()}",
        pinned=True,
        metadata={"compacted": True, "sections": len(summary.sections)},
    )


def tail_boundary(costs: Sequence[int], *, keep_tokens: int) -> int:
    """Index of the first message that survives verbatim.

    Measured on the cost of the messages that are really sent, not on the
    rendered text handed to the summarizer: a tool result is capped in the
    rendering, so measuring the tail there would leave a "compacted" context
    several times larger than the window it claims to fit. The newest message
    always survives, even when it alone exceeds ``keep_tokens``.
    """
    if not costs:
        return 0
    accumulated = 0
    boundary = len(costs)
    for index in range(len(costs) - 1, -1, -1):
        if accumulated + costs[index] > keep_tokens and boundary < len(costs):
            break
        accumulated += costs[index]
        boundary = index
    return boundary


def cap_head(head: str, head_char_cap: int) -> tuple[str, int]:
    """Bound the text handed to the summarizer, keeping its most recent part.

    The summary call is itself a model call: an unbounded head makes it the most
    expensive and slowest request of the run, and a timeout there loses the whole
    trial. Whatever is dropped is announced in the text, never silently cut, and
    the number of omitted characters travels in the decision so the report can
    state how much of the head the summary never saw.
    """
    if head_char_cap <= 0 or len(head) <= head_char_cap:
        return head, 0
    kept = head[-head_char_cap:]
    return f"{HEAD_OMITTED_MARKER}\n{kept}", len(head) - len(kept)
