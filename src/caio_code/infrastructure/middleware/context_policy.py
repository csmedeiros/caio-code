"""LangChain middleware that applies a context policy inside the agent loop.

This is the seam between the deepagents graph and the domain policies: on every
model call it maps the provider's messages to the domain, asks the pipeline what
survives, applies the decision *by index* so kept messages stay the same objects
(which is what lets the provider's prompt cache keep hitting), and publishes
``ContextShaped`` so the TUI footer and the experiment ledger see the same
numbers.

Compaction is the only step that needs a model. When a planner produced a
placeholder summary, the middleware awaits :class:`CompactionService`, swaps the
placeholder for the real anchored summary and re-measures; when no service was
injected the placeholder stays, which reads in the report as a compaction that
was planned but not executed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
from langchain_core.messages import AnyMessage

from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Transcript
from caio_code.domain.conversation.summary import SUMMARY_MESSAGE_PREFIX
from caio_code.domain.events import ContextShaped, EventBus
from caio_code.domain.policy.base import PipelineDecision, PolicyPipeline, PolicyRequest
from caio_code.domain.policy.compaction import SUMMARY_PLACEHOLDER
from caio_code.domain.ports.time import Clock
from caio_code.domain.ports.tokenizer import TokenCounter
from caio_code.infrastructure.mappers.langchain import apply_pipeline, to_domain

Handler = Callable[[ModelRequest[Any]], Any]
AsyncHandler = Callable[[ModelRequest[Any]], Awaitable[Any]]

CompactionPort = Any
"""Structural: ``await service.compact(transcript=, request=, decision=, run_id=, reason=)``."""


class ContextPolicyMiddleware(AgentMiddleware):
    """Reshapes the message list before it reaches the model."""

    def __init__(
        self,
        pipeline: PolicyPipeline,
        *,
        counter: TokenCounter,
        bus: EventBus,
        clock: Clock,
        budget: TokenBudget,
        compaction: CompactionPort | None = None,
        run_id: str = "",
        selection: Any | None = None,
        enforce_window: bool = False,
    ) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._counter = counter
        self._bus = bus
        self._clock = clock
        self._budget = budget
        self._compaction = compaction
        self._selection = selection
        self._enforce = enforce_window
        self.run_id = run_id
        self.last_decision: PipelineDecision | None = None
        self.compactions = 0
        self.truncated_tool_outputs = 0

    @property
    def name(self) -> str:
        return f"ContextPolicyMiddleware({self._pipeline.name})"

    def wrap_model_call(self, request: ModelRequest[Any], handler: Handler):
        """Synchronous path: planned and applied without a compaction model call."""
        decision, messages = self._shape(request, compaction=None)
        return handler(request.override(messages=messages) if decision else request)

    async def awrap_model_call(self, request: ModelRequest[Any], handler: AsyncHandler):
        """Asynchronous path used by the agent loop."""
        decision, messages = self._shape(request, compaction=self._compaction)
        if decision is not None and self._needs_summary(decision):
            messages = await self._run_compaction(request, decision, messages)
        return await handler(request.override(messages=messages) if decision else request)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _shape(
        self, request: ModelRequest[Any], *, compaction: CompactionPort | None
    ) -> tuple[PipelineDecision | None, list[AnyMessage]]:
        original: Sequence[AnyMessage] = request.messages
        transcript = Transcript.of(to_domain(message) for message in original)
        if not transcript:
            return None, list(original)

        system_tokens = self._fixed_tokens(request)
        task = self._task_of(transcript)
        pipeline_request = PolicyRequest(
            transcript=transcript,
            budget=self._budget,
            counter=self._counter,
            fixed_tokens=system_tokens,
            task=task,
            tool_result_char_cap=self._tool_result_cap(),
        )
        decision = self._pipeline.plan(pipeline_request)
        self.last_decision = decision
        self.truncated_tool_outputs += self._count_truncations(decision)

        self._bus.publish(
            ContextShaped(at=self._clock.now(), run_id=self.run_id, decision=decision)
        )

        if self._enforce and decision.overflowed:
            from caio_code.domain.errors import ContextOverflowError

            raise ContextOverflowError(
                required=decision.tokens_after,
                limit=decision.budget_tokens,
                policy=self._pipeline.name,
            )

        return decision, apply_pipeline(list(original), decision)

    def _needs_summary(self, decision: PipelineDecision) -> bool:
        return any(SUMMARY_PLACEHOLDER in message.text for message in decision.result().messages)

    async def _run_compaction(
        self,
        request: ModelRequest[Any],
        decision: PipelineDecision,
        messages: list[AnyMessage],
    ) -> list[AnyMessage]:
        if self._compaction is None:
            return messages

        from caio_code.infrastructure.mappers.langchain import to_langchain

        step = next(
            (item for item in decision.steps if SUMMARY_PLACEHOLDER in _injected_text(item)),
            decision.steps[-1],
        )
        transcript = Transcript.of(to_domain(message) for message in request.messages)
        pipeline_request = PolicyRequest(
            transcript=transcript,
            budget=self._budget,
            counter=self._counter,
            fixed_tokens=self._fixed_tokens(request),
            task=self._task_of(transcript),
            tool_result_char_cap=self._tool_result_cap(),
        )
        outcome = await self._compaction.compact(
            transcript=step.input_transcript,
            request=pipeline_request,
            decision=step.decision,
            run_id=self.run_id,
            reason="auto",
        )
        self.compactions += 1

        replaced = [
            to_langchain(outcome.message)
            if SUMMARY_PLACEHOLDER in _text_of(message)
            and SUMMARY_MESSAGE_PREFIX in _text_of(message)
            else message
            for message in messages
        ]
        return replaced

    def _fixed_tokens(self, request: ModelRequest[Any]) -> int:
        total = 0
        if request.system_message is not None:
            total += self._counter.count_text(_text_of(request.system_message))
        for tool in request.tools or ():
            schema = getattr(tool, "args_schema", None)
            total += self._counter.count_text(getattr(tool, "name", "") or "")
            if schema is not None:
                total += self._counter.count_text(str(schema))
        return total

    def _task_of(self, transcript: Transcript) -> str:
        for message in transcript:
            if message.role.value == "user" and message.text.strip():
                return message.text
        return ""

    def _tool_result_cap(self) -> int:
        from caio_code.config import CompactionConfig

        return CompactionConfig().tool_result_char_cap

    def _count_truncations(self, decision: PipelineDecision) -> int:
        return sum(
            len(step.decision.detail.get("truncated_messages", ())) for step in decision.steps
        )


def _injected_text(step: Any) -> str:
    return " ".join(message.text for message in step.decision.injected)


def _text_of(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return str(content)
