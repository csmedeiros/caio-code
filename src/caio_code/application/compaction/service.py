"""Compaction use case: plan, summarize, replace, account.

The domain planner decides what is folded and writes the prompt; this service is
the only place that calls a model for it, parses the answer into an
:class:`AnchoredSummary`, measures what the summary cost, and hands back the
message that replaces the head of the transcript.

An empty or unparsable summary is a failure of the compaction, not of the run:
the service returns ``well_formed=False`` and the caller keeps the head it
already had, so a bad summary degrades into "no compaction" instead of silently
destroying the context.
"""

from __future__ import annotations

from dataclasses import dataclass

from caio_code.domain.conversation.messages import Message, Transcript
from caio_code.domain.conversation.summary import AnchoredSummary, parse_summary
from caio_code.domain.errors import SummarizerError
from caio_code.domain.events import CompactionEnded, CompactionStarted, EventBus
from caio_code.domain.policy.base import PolicyDecision, PolicyRequest
from caio_code.domain.policy.compaction import SUMMARY_PLACEHOLDER, summary_message_from
from caio_code.domain.ports.summarizer import Summarizer
from caio_code.domain.ports.time import Clock
from caio_code.domain.ports.tokenizer import TokenCounter
from caio_code.domain.usage.accounting import Cost, PriceSheet, TokenUsage

SUMMARY_MESSAGE_ID = "compaction:summary"
DEFAULT_SUMMARY_MAX_TOKENS = 4_096
"""Ceiling for the summary text, mirrored from CompactionConfig.summary_max_tokens."""


@dataclass(frozen=True, slots=True)
class CompactionOutcome:
    """Result of one compaction."""

    summary: AnchoredSummary
    message: Message
    usage: TokenUsage
    cost: Cost
    latency_ms: int
    well_formed: bool
    head_chars: int
    tokens_before: int
    tokens_after: int
    reason: str

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before - self.tokens_after)

    def as_record(self) -> dict[str, object]:
        return {
            "summary_chars": len(self.summary.raw),
            "sections": len(self.summary.sections),
            "well_formed": self.well_formed,
            "missing_sections": list(self.summary.missing_sections()),
            "head_chars": self.head_chars,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "cached_input_tokens": self.usage.cached_input_tokens,
            },
            "cost_usd": self.cost.as_float(),
            "latency_ms": self.latency_ms,
            "reason": self.reason,
        }


class CompactionService:
    """Runs one compaction end to end."""

    def __init__(
        self,
        summarizer: Summarizer,
        counter: TokenCounter,
        clock: Clock,
        bus: EventBus,
        pricing: PriceSheet | None = None,
        *,
        summary_message_id: str = SUMMARY_MESSAGE_ID,
        summary_max_tokens: int = DEFAULT_SUMMARY_MAX_TOKENS,
    ) -> None:
        self._summarizer = summarizer
        self._counter = counter
        self._clock = clock
        self._bus = bus
        self._pricing = pricing
        self._message_id = summary_message_id
        if summary_max_tokens <= 0:
            msg = f"summary_max_tokens must be positive, got {summary_max_tokens}"
            raise ValueError(msg)
        self._summary_max_tokens = summary_max_tokens

    async def compact(
        self,
        *,
        transcript: Transcript,
        request: PolicyRequest,
        decision: PolicyDecision,
        run_id: str,
        reason: str = "auto",
    ) -> CompactionOutcome:
        """Summarize the head the planner chose and build the replacement message."""
        prompt = self._prompt_of(decision)
        head_chars = int(decision.detail.get("head_chars", 0))

        self._bus.publish(
            CompactionStarted(
                at=self._clock.now(),
                run_id=run_id,
                head_chars=head_chars,
                previous_summary=request.previous_summary is not None,
                reason=reason,
            )
        )

        started = self._clock.monotonic_ms()
        result = await self._summarizer.asummarize(prompt, max_tokens=self._summary_max_tokens)
        latency_ms = max(0, self._clock.monotonic_ms() - started)

        summary = parse_summary(result.text)
        message = summary_message_from(decision, summary, message_id=self._message_id)
        cost = self._cost_of(result.usage, result.model)

        shaped = decision.result(transcript)
        replaced = self._with_summary(shaped, message)
        tokens_before = decision.tokens_before
        tokens_after = self._counter.count_transcript(replaced) + request.fixed_tokens

        self._bus.publish(
            CompactionEnded(
                at=self._clock.now(),
                run_id=run_id,
                summary_chars=len(summary.raw),
                sections=len(summary.sections),
                well_formed=summary.is_well_formed,
                usage=result.usage,
                cost=cost,
                latency_ms=latency_ms,
                reason=reason,
            )
        )

        return CompactionOutcome(
            summary=summary,
            message=message,
            usage=result.usage,
            cost=cost,
            latency_ms=latency_ms,
            well_formed=summary.is_well_formed,
            head_chars=head_chars,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            reason=reason,
        )

    def compact_sync(
        self,
        *,
        transcript: Transcript,
        request: PolicyRequest,
        decision: PolicyDecision,
        run_id: str,
        reason: str = "auto",
    ) -> CompactionOutcome:
        """Synchronous variant for the CLI and for the evaluation harness."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.compact(
                    transcript=transcript,
                    request=request,
                    decision=decision,
                    run_id=run_id,
                    reason=reason,
                )
            )
        if loop.is_running():
            msg = "compact_sync cannot run inside a running event loop; await compact()"
            raise SummarizerError(msg)
        return asyncio.run(
            self.compact(
                transcript=transcript,
                request=request,
                decision=decision,
                run_id=run_id,
                reason=reason,
            )
        )

    def _prompt_of(self, decision: PolicyDecision) -> str:
        for message in decision.injected:
            prompt = message.metadata.get("compaction_prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt
        msg = f"compaction decision carries no prompt (policy {decision.policy!r})"
        raise SummarizerError(msg)

    def _cost_of(self, usage: TokenUsage, model: str) -> Cost:
        if self._pricing is None:
            return Cost.zero()
        return self._pricing.cost_of(usage, model)

    def _with_summary(self, shaped: Transcript, message: Message) -> Transcript:
        replaced = [
            message if SUMMARY_PLACEHOLDER in item.text and item.id == self._message_id else item
            for item in shaped
        ]
        return Transcript.of(replaced)


