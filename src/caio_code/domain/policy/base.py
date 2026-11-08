"""The context-policy contract.

A policy is a pure planner: it looks at a transcript and a budget and returns a
*decision* (keep these indices, drop those, substitute this one), never a new
provider-specific message list and never an I/O call. The caller applies the
decision, which keeps every policy testable with plain data and lets the
infrastructure middleware apply it to LangChain messages by index without a
lossy round trip.

All decisions report their own overflow. A policy that cannot fit the budget
says so; nothing downstream hides it by truncating after the measurement.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Transcript
from caio_code.domain.conversation.summary import AnchoredSummary
from caio_code.domain.ports.tokenizer import TokenCounter

DEFAULT_TOOL_RESULT_CHAR_CAP = 2_000


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    """Everything a policy may look at.

    ``fixed_tokens`` is the cost the policy cannot touch: system prompt and tool
    schemas. It is subtracted from the budget before shaping, so the shaped
    transcript plus the fixed cost is what has to fit.
    """

    transcript: Transcript
    budget: TokenBudget
    counter: TokenCounter
    fixed_tokens: int = 0
    task: str = ""
    scores: Sequence[float] | None = None
    previous_summary: AnchoredSummary | None = None
    tool_result_char_cap: int = DEFAULT_TOOL_RESULT_CHAR_CAP

    def __post_init__(self) -> None:
        if self.fixed_tokens < 0:
            msg = f"fixed_tokens must be non-negative, got {self.fixed_tokens}"
            raise ValueError(msg)
        if self.scores is not None and len(self.scores) != len(self.transcript):
            msg = (
                f"scores has {len(self.scores)} entries for "
                f"{len(self.transcript)} messages"
            )
            raise ValueError(msg)

    @property
    def available_tokens(self) -> int:
        """Budget left for the transcript itself."""
        return max(0, self.budget.tokens - self.fixed_tokens)

    def costs(self) -> list[int]:
        """Per-message token cost, in transcript order."""
        return [self.counter.count_message(message) for message in self.transcript]


@dataclass(frozen=True, slots=True)
class Removal:
    """One message a policy decided to drop."""

    index: int
    reason: str


@dataclass(frozen=True, slots=True)
class Substitution:
    """One message a policy decided to rewrite in place."""

    index: int
    message: Message
    reason: str


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The plan a policy produced, and its measured cost."""

    policy: str
    kept_indices: tuple[int, ...]
    counter: TokenCounter
    removals: tuple[Removal, ...] = ()
    substitutions: tuple[Substitution, ...] = ()
    injected: tuple[Message, ...] = ()
    insert_at: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    budget_tokens: int = 0
    notes: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def overflow_tokens(self) -> int:
        return max(0, self.tokens_after - self.budget_tokens)

    @property
    def overflowed(self) -> bool:
        return self.tokens_after > self.budget_tokens

    @property
    def dropped(self) -> int:
        return len(self.removals)

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    def result(self, transcript: Transcript) -> Transcript:
        """Apply the decision, producing the transcript the model will see."""
        by_index = {substitution.index: substitution.message for substitution in self.substitutions}
        kept = [
            by_index.get(index, transcript[index])
            for index in sorted(self.kept_indices)
            if 0 <= index < len(transcript)
        ]
        insert_at = max(0, min(self.insert_at, len(kept)))
        return Transcript.of((*kept[:insert_at], *self.injected, *kept[insert_at:]))

    def as_record(self) -> dict[str, Any]:
        """Serializable form, for reports and for the TUI context inspector."""
        return {
            "policy": self.policy,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "budget_tokens": self.budget_tokens,
            "overflow_tokens": self.overflow_tokens,
            "tokens_saved": self.tokens_saved,
            "kept": len(self.kept_indices),
            "dropped": self.dropped,
            "substituted": len(self.substitutions),
            "injected": len(self.injected),
            "notes": list(self.notes),
            **self.detail,
        }


@runtime_checkable
class ContextPolicy(Protocol):
    """A context-management strategy."""

    @property
    def name(self) -> str:
        """Stable identifier used in reports and in the CLI."""

    def plan(self, request: PolicyRequest) -> PolicyDecision:
        """Decide what survives, purely from the request."""


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """One step of a pipeline: what it was planned on, what it decided, what it produced.

    ``input_transcript`` is not redundant. A decision's indices refer to the
    transcript it was planned on, so re-applying that decision to the step's
    *output* silently drops every index out of range - which is exactly how a
    compaction ends up measuring its summary against the wrong context.
    """

    decision: PolicyDecision
    transcript: Transcript
    input_transcript: Transcript


@dataclass(frozen=True, slots=True)
class PipelineDecision:
    """Composed decision of several policies applied in order.

    Composition is how tool-output truncation is combined with any other
    strategy: truncation runs first, shrinking the input the next policy has to
    fit, and every step keeps its own numbers so the contribution of each is
    visible in the report.
    """

    name: str
    steps: tuple[StepOutcome, ...]
    tokens_before: int
    tokens_after: int
    budget_tokens: int

    @property
    def overflow_tokens(self) -> int:
        return max(0, self.tokens_after - self.budget_tokens)

    @property
    def overflowed(self) -> bool:
        return self.tokens_after > self.budget_tokens

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    @property
    def policies(self) -> tuple[str, ...]:
        return tuple(step.decision.policy for step in self.steps)

    @property
    def final(self) -> PolicyDecision:
        return self.steps[-1].decision

    def result(self) -> Transcript:
        return self.steps[-1].transcript

    def as_record(self) -> dict[str, Any]:
        return {
            "pipeline": self.name,
            "policies": list(self.policies),
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "budget_tokens": self.budget_tokens,
            "overflow_tokens": self.overflow_tokens,
            "tokens_saved": self.tokens_saved,
            "steps": [step.decision.as_record() for step in self.steps],
        }


class PolicyPipeline:
    """Applies policies in order, threading the transcript and the budget."""

    def __init__(self, name: str, steps: Sequence[ContextPolicy]) -> None:
        if not steps:
            msg = "a pipeline needs at least one policy"
            raise ValueError(msg)
        self._name = name
        self._steps = tuple(steps)

    @property
    def name(self) -> str:
        return self._name

    @property
    def policies(self) -> tuple[str, ...]:
        return tuple(step.name for step in self._steps)

    def plan(self, request: PolicyRequest) -> PipelineDecision:
        transcript = request.transcript
        tokens_before = request.counter.count_transcript(transcript)
        tokens_after = tokens_before
        outcomes: list[StepOutcome] = []

        for policy in self._steps:
            step_request = PolicyRequest(
                transcript=transcript,
                budget=request.budget,
                counter=request.counter,
                fixed_tokens=request.fixed_tokens,
                task=request.task,
                scores=request.scores if len(request.scores or ()) == len(transcript) else None,
                previous_summary=request.previous_summary,
                tool_result_char_cap=request.tool_result_char_cap,
            )
            decision = policy.plan(step_request)
            step_input = transcript
            transcript = decision.result(step_input)
            tokens_after = request.counter.count_transcript(transcript)
            outcomes.append(
                StepOutcome(
                    decision=decision, transcript=transcript, input_transcript=step_input
                )
            )

        return PipelineDecision(
            name=self._name,
            steps=tuple(outcomes),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            budget_tokens=request.budget.tokens,
        )
