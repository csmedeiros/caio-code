"""The chat-replay experiment: seed, shape once, probe in-band, judge.

One trial is: seed the case's full overflowing history, run the arm's policy
pipeline exactly once (compaction arms summarize here, once), then ask the
case's probes as ordinary user turns **to the same conversation** -- no probe
system prompt, no JSON contract. The agent may call tools before answering; the
calls are served by :class:`ReplayToolServer` from the case's own recorded
interactions and the variant's spill files, capped per trial. An LLM judge that
never sees the context grades each answer binary correct/incorrect.

Two invariants the harness enforces rather than hopes for:

* the seeded history **must** overflow the declared window, so the shaping step
  always fires (a case that fits measures nothing and stops the run);
* exactly one shaping step per trial -- the probe round runs immediately after
  the first shaped context and the trial ends after grading.

Accounting keeps the split the thesis reports honestly: ``probe_usage`` is what
the agent model was sent (shaped context, probe turns and tool turns);
``aux_usage`` is what shaping and grading cost (summarizer, decision scorer,
judge) and is never summed into the prompt column.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from caio_code.application.compaction.service import CompactionService
from caio_code.application.evaluation.judge import (
    JudgeOutcome,
    LlmJudge,
    judge_items_for,
    load_judge_prompt,
)
from caio_code.application.evaluation.replay_report import write_replay_report
from caio_code.application.evaluation.replay_tools import ReplayToolServer
from caio_code.application.experiment.arms import ArmSpec, select_arms
from caio_code.application.experiment.runner import (
    _close_progress,
    _open_progress,
    _record_progress,
    _sum,
    _total_cost,
)
from caio_code.application.selection.service import SelectionService
from caio_code.config import Settings
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.errors import ConfigurationError, EvaluationError
from caio_code.domain.evaluation.cases import (
    VARIANTS,
    CaseVariant,
    EvalDataset,
    HistoryCase,
)
from caio_code.domain.evaluation.scoring import (
    ArmAggregate,
    ExperimentReport,
    ProbeScore,
    TrialResult,
)
from caio_code.domain.evaluation.spill import variant_case
from caio_code.domain.events import EventBus, InMemoryEventBus, RunFinished, RunStarted
from caio_code.domain.policy.base import PipelineDecision, PolicyPipeline, PolicyRequest
from caio_code.domain.policy.compaction import SUMMARY_PLACEHOLDER
from caio_code.domain.ports.gateway import ModelGateway, ModelReply, ToolSchema
from caio_code.domain.ports.scorer import RelevanceScorer
from caio_code.domain.ports.summarizer import Summarizer
from caio_code.domain.ports.time import Clock, IdentifierFactory
from caio_code.domain.ports.tokenizer import TokenCounter
from caio_code.domain.usage.accounting import CacheStats, Cost, PriceSheet, TokenUsage

REPLAY_ARMS = (
    "baseline_full_history",
    "sliding_window",
    "message_selection",
    "anchored_compaction",
    "message_selection_decision",
)
"""The five arms of the Chapter 4 replay run (truncation is the case variant, not an arm)."""

ANSWER_SNIPPET_CAP = 400
"""Chars of the agent reply kept per probe score; the full reply lives in ``replay``."""

CAP_REACHED_TEMPLATE = (
    "ToolUnavailableInReplay: the probe round's tool-call cap ({cap}) is reached. "
    "Answer from the conversation content you have."
)


@dataclass(frozen=True, slots=True)
class ReplayDependencies:
    """Everything the replay runner needs, injected."""

    settings: Settings
    dataset: EvalDataset
    counter: TokenCounter
    gateway: ModelGateway
    judge: LlmJudge
    pricing: PriceSheet
    clock: Clock
    identifiers: IdentifierFactory
    bus: EventBus = field(default_factory=InMemoryEventBus)
    summarizer: Summarizer | None = None
    scorer: RelevanceScorer | None = None
    decision_scorer: RelevanceScorer | None = None
    decision_model: str = ""


@dataclass(frozen=True, slots=True)
class ReplayRun:
    """Outcome of one replay experiment."""

    report: ExperimentReport
    trials: tuple[TrialResult, ...]
    directory: Path | None


class ChatReplayRunner:
    """Runs arms x cases x variants x repetitions of the chat replay."""

    def __init__(self, deps: ReplayDependencies) -> None:
        self._deps = deps

    async def run(
        self,
        *,
        arms: Sequence[ArmSpec],
        variants: Sequence[CaseVariant],
        repetitions: int,
        cases: int | None = None,
        concurrency: int = 1,
        run_id: str | None = None,
        out: Path | None = None,
    ) -> ReplayRun:
        if repetitions < 1:
            msg = f"repetitions must be at least 1, got {repetitions}"
            raise EvaluationError(msg)
        if concurrency < 1:
            msg = f"concurrency must be at least 1, got {concurrency}"
            raise EvaluationError(msg)
        unknown = [variant for variant in variants if variant not in VARIANTS]
        if unknown:
            msg = f"unknown case variants: {unknown}; expected one of {list(VARIANTS)}"
            raise EvaluationError(msg)

        dataset = self._deps.dataset.limited(cases) if cases else self._deps.dataset
        resolved_run_id = run_id or self._deps.identifiers.run_id()
        started_at = self._deps.clock.now().isoformat()

        # Overflow guarantee: every (case, variant) must exceed every arm's
        # declared window, so the shaping step always fires. Checked before any
        # money is spent.
        self._assert_overflow(dataset, arms, variants)

        tasks = [
            (arm, case, variant, repetition)
            for arm in arms
            for case in dataset.cases
            for variant in variants
            for repetition in range(1, repetitions + 1)
        ]
        semaphore = asyncio.Semaphore(concurrency)
        progress_dir = Path(out) / resolved_run_id if out is not None else None
        progress_path = _open_progress(progress_dir)
        completed = 0
        total = len(tasks)

        async def guarded(
            arm: ArmSpec, case: HistoryCase, variant: CaseVariant, repetition: int
        ) -> TrialResult:
            nonlocal completed
            async with semaphore:
                trial = await self.run_trial(
                    arm, case, variant, repetition, run_id=resolved_run_id
                )
            completed += 1
            _record_progress(progress_path, trial, completed, total)
            return trial

        trials = list(await asyncio.gather(*(guarded(*task) for task in tasks)))
        _close_progress(progress_path)
        finished_at = self._deps.clock.now().isoformat()

        # One aggregate per (arm, variant): the truncation factor is a column of
        # the report, never averaged away.
        aggregates = tuple(
            ArmAggregate(
                arm=arm.name,
                model=self._deps.gateway.model,
                trials=tuple(
                    trial
                    for trial in trials
                    if trial.arm == arm.name and trial.variant == variant
                ),
                repetitions=repetitions,
                variant=variant,
            )
            for arm in arms
            for variant in variants
        )
        total_cost = Cost.zero()
        for aggregate in aggregates:
            total_cost = total_cost + aggregate.total_cost

        report = ExperimentReport(
            run_id=resolved_run_id,
            dataset=dataset.name,
            model=self._deps.gateway.model,
            arms=aggregates,
            window_tokens=self._deps.settings.window.tokens,
            repetitions=repetitions,
            seed=self._deps.settings.evaluation.seed,
            started_at=started_at,
            finished_at=finished_at,
            total_cost=total_cost,
        )

        directory = None
        if out is not None:
            directory = write_replay_report(report, trials, Path(out) / resolved_run_id)
        return ReplayRun(report=report, trials=tuple(trials), directory=directory)

    def _assert_overflow(
        self,
        dataset: EvalDataset,
        arms: Sequence[ArmSpec],
        variants: Sequence[CaseVariant],
    ) -> None:
        window = min(arm.window_tokens for arm in arms) if arms else 0
        for case in dataset.cases:
            for variant in variants:
                shaped_case = variant_case(
                    case,
                    variant,
                    max_bytes=self._deps.settings.tool_output.max_bytes,
                )
                tokens = self._deps.counter.count_transcript(shaped_case.transcript)
                if tokens <= window:
                    msg = (
                        f"case {case.id!r} variant {variant!r} holds {tokens} proxy "
                        f"tokens, which does not overflow the declared window of "
                        f"{window}; the shaping step would never fire. Lower "
                        f"--window-tokens or use a larger case."
                    )
                    raise EvaluationError(msg)

    async def run_trial(
        self,
        arm: ArmSpec,
        case: HistoryCase,
        variant: CaseVariant,
        repetition: int,
        *,
        run_id: str = "",
    ) -> TrialResult:
        """One seeded replay: shape once, probe in-band, judge, account."""
        replay_case = variant_case(
            case, variant, max_bytes=self._deps.settings.tool_output.max_bytes
        )
        trial_id = f"{run_id or 'run'}:{arm.name}:{case.id}:{variant}:{repetition}"
        started = self._deps.clock.monotonic_ms()
        self._deps.bus.publish(
            RunStarted(
                at=self._deps.clock.now(),
                run_id=trial_id,
                task=replay_case.task,
                model=self._deps.gateway.model,
                policy=arm.name,
            )
        )

        pipeline = arm.pipeline(self._deps.settings)
        try:
            request, scorer_usages = await self._build_request(arm, replay_case, pipeline)
            transcript = request.transcript
            tokens_before = request.counter.count_transcript(transcript) + request.fixed_tokens
            decision = pipeline.plan(request)
            shaped, compaction_usage, compaction_cost, compactions = await self._apply_compaction(
                arm=arm,
                decision=decision,
                request=request,
                trial_id=trial_id,
            )
        except Exception as exc:  # recorded as a trial error, never swallowed
            return self._failed_trial(
                trial_id, arm, replay_case, variant, repetition, started,
                f"{type(exc).__name__} while shaping the context: {exc}",
            )

        tokens_after = request.counter.count_transcript(shaped) + request.fixed_tokens
        overflow_tokens = max(0, tokens_after - decision.budget_tokens)
        scorer_cost = _total_cost(
            self._deps.pricing,
            scorer_usages,
            self._deps.decision_model or self._deps.gateway.model,
        )

        server = ReplayToolServer(replay_case)
        cap = self._deps.settings.evaluation.probe_tool_call_cap
        try:
            reply_text, probe_usages, probe_cost = await self._probe_round(
                shaped, replay_case, server, cap=cap
            )
        except Exception as exc:  # recorded as a trial error, never swallowed
            return self._failed_trial(
                trial_id, arm, replay_case, variant, repetition, started,
                f"provider error during the probe round: {exc}",
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                overflow_tokens=overflow_tokens,
                decision=decision,
                shaped=shaped,
                extra_usage=[*compaction_usage, *scorer_usages],
                extra_cost=compaction_cost + scorer_cost,
                compactions=compactions,
                server=server,
            )

        try:
            outcome: JudgeOutcome = await self._deps.judge.agrade(
                judge_items_for(replay_case.probes, reply_text)
            )
        except Exception as exc:  # recorded as a trial error, never swallowed
            return self._failed_trial(
                trial_id, arm, replay_case, variant, repetition, started,
                f"judge error: {exc}",
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                overflow_tokens=overflow_tokens,
                decision=decision,
                shaped=shaped,
                extra_usage=[*compaction_usage, *scorer_usages, *probe_usages],
                extra_cost=compaction_cost + scorer_cost + probe_cost,
                compactions=compactions,
                server=server,
            )

        judge_cost = self._deps.pricing.cost_of(outcome.usage, outcome.model)
        positions = {
            probe.fact_id: replay_case.fact(probe.fact_id).position
            for probe in replay_case.probes
        }
        probes = tuple(
            ProbeScore(
                probe_id=probe.id,
                fact_id=probe.fact_id,
                position=positions.get(probe.fact_id, "middle"),
                correct=verdict.correct,
                answer=reply_text[:ANSWER_SNIPPET_CAP],
                expected=probe.expected,
            )
            for probe, verdict in zip(replay_case.probes, outcome.verdicts, strict=True)
        )

        aux_usages = [*compaction_usage, *scorer_usages, outcome.usage]
        usages = [*probe_usages, *aux_usages]
        usage = _sum(usages)
        probe_usage = _sum(probe_usages)
        cost = probe_cost + compaction_cost + scorer_cost + judge_cost
        latency = max(0, self._deps.clock.monotonic_ms() - started)

        trial = TrialResult(
            trial_id=trial_id,
            case_id=case.id,
            arm=arm.name,
            repetition=repetition,
            probes=probes,
            usage=usage,
            cache=CacheStats.from_usages(usages),
            cost=cost,
            model=self._deps.gateway.model,
            variant=variant,
            probe_usage=probe_usage,
            aux_usage=_sum(aux_usages),
            latency_ms=latency,
            messages_in=len(transcript),
            messages_after_policy=len(shaped),
            tokens_before_policy=tokens_before,
            tokens_after_policy=tokens_after,
            budget_tokens=decision.budget_tokens,
            overflow_tokens=overflow_tokens,
            compactions=compactions,
            truncated_tool_outputs=_truncation_count(decision),
            policy_record={
                **decision.as_record(),
                "scorer": {
                    "kind": arm.scorer_kind,
                    "model": self._deps.decision_model or self._deps.gateway.model,
                    "input_tokens": sum(u.input_tokens for u in scorer_usages),
                    "output_tokens": sum(u.output_tokens for u in scorer_usages),
                    "cost_usd": scorer_cost.as_float(),
                },
            },
            replay={
                "tools": server.stats.as_record(),
                "agent_reply": reply_text,
                "agent_calls": len(probe_usages),
                "judge": {
                    "model": outcome.model,
                    "usage": {
                        "input_tokens": outcome.usage.input_tokens,
                        "output_tokens": outcome.usage.output_tokens,
                    },
                    "cost_usd": judge_cost.as_float(),
                    "verdicts": [
                        {
                            "probe_id": verdict.probe_id,
                            "correct": verdict.correct,
                            "reason": verdict.reason,
                        }
                        for verdict in outcome.verdicts
                    ],
                },
            },
        )
        self._publish_finished(trial_id, trial)
        return trial

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    async def _build_request(
        self, arm: ArmSpec, case: HistoryCase, pipeline: PolicyPipeline
    ) -> tuple[PolicyRequest, list[TokenUsage]]:
        settings = self._deps.settings
        request = PolicyRequest(
            transcript=case.transcript,
            budget=TokenBudget(arm.window_tokens),
            counter=self._deps.counter,
            task=case.task,
            tool_result_char_cap=settings.compaction.tool_result_char_cap,
        )
        if not arm.needs_scores:
            return request, []
        scorer = self._scorer_for(arm)
        threshold = (
            settings.decision.relevance_threshold if arm.scorer_kind == "decision" else None
        )
        service = SelectionService(scorer, threshold=threshold)
        request = await service.with_scores(request, task=case.task)
        outcome = service.last_outcome
        usages = list(outcome.usages) if outcome is not None else []
        return request, usages

    def _scorer_for(self, arm: ArmSpec) -> RelevanceScorer:
        if arm.scorer_kind == "decision":
            if self._deps.decision_scorer is None:
                msg = f"arm {arm.name!r} needs a decision-model scorer but none was injected"
                raise ConfigurationError(msg)
            return self._deps.decision_scorer
        if self._deps.scorer is None:
            msg = f"arm {arm.name!r} needs a scorer but none was injected"
            raise ConfigurationError(msg)
        return self._deps.scorer

    async def _apply_compaction(
        self,
        *,
        arm: ArmSpec,
        decision: PipelineDecision,
        request: PolicyRequest,
        trial_id: str,
    ) -> tuple[Transcript, list[TokenUsage], Cost, int]:
        """Run the summarizer exactly once, when the plan left a placeholder."""
        shaped = decision.result()
        if SUMMARY_PLACEHOLDER not in _all_text(shaped):
            return shaped, [], Cost.zero(), 0
        if self._deps.summarizer is None:
            msg = f"arm {arm.name!r} needs a summarizer but none was injected"
            raise ConfigurationError(msg)

        service = CompactionService(
            self._deps.summarizer,
            self._deps.counter,
            self._deps.clock,
            self._deps.bus,
            self._deps.pricing,
            summary_max_tokens=self._deps.settings.compaction.summary_max_tokens,
        )
        step = next(
            (item for item in decision.steps if SUMMARY_PLACEHOLDER in _all_text(item.transcript)),
            decision.steps[-1],
        )
        outcome = await service.compact(
            transcript=step.input_transcript,
            request=request,
            decision=step.decision,
            run_id=trial_id,
            reason="replay-evaluation",
        )
        replaced = Transcript.of(
            outcome.message if SUMMARY_PLACEHOLDER in message.text else message
            for message in shaped
        )
        return replaced, [outcome.usage], outcome.cost, 1

    def _probe_message(self, case: HistoryCase) -> Message:
        questions = "\n".join(
            f"- {probe.id}: {probe.question}" for probe in case.probes
        )
        return Message(
            id=self._deps.identifiers.message_id(),
            role=Role.USER,
            text=(
                "Before we continue, answer these questions about the session so far. "
                "Answer each one from what the session contains, naming the exact value, "
                "path, name or number; say you do not know when it is not there:\n"
                f"{questions}"
            ),
            pinned=True,
        )

    async def _probe_round(
        self,
        shaped: Transcript,
        case: HistoryCase,
        server: ReplayToolServer,
        *,
        cap: int,
    ) -> tuple[str, list[TokenUsage], Cost]:
        """Ask the probes in-band; serve tool calls up to the cap; return the answer."""
        messages: list[Message] = [*shaped.messages, self._probe_message(case)]
        usages: list[TokenUsage] = []
        cost = Cost.zero()
        calls_served = 0
        # Hard stop so a model that keeps asking for tools cannot loop forever:
        # after the cap no tools are offered, and one extra turn bounds a model
        # that still emits calls.
        max_turns = cap + 2
        for _ in range(max_turns):
            tools = self._offered_tools(server, calls_served, cap)
            reply: ModelReply = await self._deps.gateway.acomplete(messages, tools=tools)
            usages.append(reply.usage)
            cost = cost + self._deps.pricing.cost_of(reply.usage, reply.model)
            if not reply.wants_tools:
                return reply.text, usages, cost

            assistant_id = self._deps.identifiers.message_id()
            messages.append(
                Message(
                    id=assistant_id,
                    role=Role.ASSISTANT,
                    text=reply.text,
                    tool_calls=reply.tool_calls,
                )
            )
            for call in reply.tool_calls:
                if calls_served < cap:
                    outcome = server.serve(call)
                    text = outcome.text
                    calls_served += 1
                else:
                    text = CAP_REACHED_TEMPLATE.format(cap=cap)
                messages.append(
                    Message(
                        id=self._deps.identifiers.message_id(),
                        role=Role.TOOL,
                        text=text,
                        tool_call_id=call.id,
                    )
                )
        msg = (
            f"the probe round did not produce a final answer within {max_turns} "
            f"turns (tool-call cap {cap})"
        )
        raise EvaluationError(msg)

    def _offered_tools(
        self, server: ReplayToolServer, calls_served: int, cap: int
    ) -> tuple[ToolSchema, ...] | None:
        if calls_served >= cap or not server.has_surface:
            return None
        return server.tool_schemas

    def _failed_trial(
        self,
        trial_id: str,
        arm: ArmSpec,
        case: HistoryCase,
        variant: CaseVariant,
        repetition: int,
        started: int,
        error: str,
        *,
        tokens_before: int = 0,
        tokens_after: int | None = None,
        overflow_tokens: int = 0,
        decision: PipelineDecision | None = None,
        shaped: Transcript | None = None,
        extra_usage: Sequence[TokenUsage] = (),
        extra_cost: Cost | None = None,
        compactions: int = 0,
        server: ReplayToolServer | None = None,
    ) -> TrialResult:
        usages = list(extra_usage)
        usage = _sum(usages)
        trial = TrialResult(
            trial_id=trial_id,
            case_id=case.id,
            arm=arm.name,
            repetition=repetition,
            probes=tuple(
                ProbeScore(
                    probe_id=probe.id,
                    fact_id=probe.fact_id,
                    position=case.fact(probe.fact_id).position,
                    correct=False,
                    answer="",
                    expected=probe.expected,
                )
                for probe in case.probes
            ),
            usage=usage,
            cache=CacheStats.from_usages(usages),
            cost=extra_cost or Cost.zero(),
            model=self._deps.gateway.model,
            variant=variant,
            aux_usage=usage,
            latency_ms=max(0, self._deps.clock.monotonic_ms() - started),
            messages_in=len(case.transcript),
            messages_after_policy=len(shaped) if shaped is not None else 0,
            tokens_before_policy=tokens_before,
            tokens_after_policy=(
                tokens_after
                if tokens_after is not None
                else (decision.tokens_after if decision else tokens_before)
            ),
            budget_tokens=decision.budget_tokens if decision else 0,
            overflow_tokens=overflow_tokens,
            compactions=compactions,
            truncated_tool_outputs=_truncation_count(decision) if decision else 0,
            error=error,
            policy_record=decision.as_record() if decision else {},
            replay={"tools": server.stats.as_record()} if server is not None else {},
        )
        self._publish_finished(trial_id, trial)
        return trial

    def _publish_finished(self, trial_id: str, trial: TrialResult) -> None:
        self._deps.bus.publish(
            RunFinished(
                at=self._deps.clock.now(),
                run_id=trial_id,
                status="error" if trial.error else "completed",
                usage=trial.usage,
                cost=trial.cost,
                compactions=trial.compactions,
                error=trial.error,
            )
        )


def _all_text(transcript: Transcript) -> str:
    return "\n".join(message.text for message in transcript)


def _truncation_count(decision: PipelineDecision) -> int:
    return sum(len(step.decision.detail.get("truncated_messages", ())) for step in decision.steps)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def build_replay_dependencies(
    settings: Settings,
    *,
    dataset: EvalDataset | None = None,
    bus: EventBus | None = None,
    clock: Clock | None = None,
    identifiers: IdentifierFactory | None = None,
    counter: TokenCounter | None = None,
    gateway: ModelGateway | None = None,
    judge: LlmJudge | None = None,
    summarizer: Summarizer | None = None,
    scorer: RelevanceScorer | None = None,
    pricing: PriceSheet | None = None,
) -> ReplayDependencies:
    """Composition root for the replay experiment; every part is overridable."""
    from caio_code.infrastructure.datasets.loader import load_dataset
    from caio_code.infrastructure.decision.factory import build_decision_scorer
    from caio_code.infrastructure.llm.factory import (
        build_gateway,
        build_scorer,
        build_summarizer,
    )
    from caio_code.infrastructure.llm.stub import StubScorer
    from caio_code.infrastructure.observability.clocks import (
        SequentialIdentifiers,
        SystemClock,
    )
    from caio_code.infrastructure.pricing.sheet import pricing_for
    from caio_code.infrastructure.tokens.counter import build_counter

    resolved_counter = counter or build_counter(
        settings.tokens.counter,
        chars_per_token=settings.tokens.chars_per_token,
        encoding=settings.tokens.tiktoken_encoding,
    )
    resolved_gateway = gateway or build_gateway(settings, clock=clock)
    lexical = StubScorer()
    resolved_scorer = scorer or build_scorer(settings, fallback=lexical, clock=clock)
    resolved_decision_scorer = build_decision_scorer(settings, fallback=lexical, clock=clock)
    decision_model = settings.decision.model if settings.decision.provider != "stub" else ""
    if judge is None:
        from caio_code.infrastructure.llm.stub import StubJudgeGateway

        aux_kind = settings.provider.aux_provider or settings.provider.provider
        judge_gateway: ModelGateway = (
            StubJudgeGateway(clock=clock or SystemClock())
            if aux_kind == "stub"
            else build_gateway(settings, auxiliary=True, clock=clock)
        )
        judge = LlmJudge(
            gateway=judge_gateway,
            prompt_template=load_judge_prompt(
                Path(settings.evaluation.judge_prompt_path)
            ),
        )
    return ReplayDependencies(
        settings=settings,
        dataset=dataset
        or load_dataset(
            Path(settings.evaluation.dataset_dir), limit=settings.evaluation.max_cases
        ),
        counter=resolved_counter,
        gateway=resolved_gateway,
        judge=judge,
        pricing=pricing or pricing_for(settings),
        clock=clock or SystemClock(),
        identifiers=identifiers or SequentialIdentifiers(prefix="replay"),
        bus=bus or InMemoryEventBus(),
        summarizer=summarizer or build_summarizer(settings, clock=clock),
        scorer=resolved_scorer,
        decision_scorer=resolved_decision_scorer,
        decision_model=decision_model,
    )


def resolve_variants(raw: Sequence[str] | None) -> tuple[CaseVariant, ...]:
    """Parse ``--variants``; an unknown name lists what is available."""
    if not raw:
        return ("full",)
    unknown = [name for name in raw if name not in VARIANTS]
    if unknown:
        msg = f"unknown variants {unknown}; available: {list(VARIANTS)}"
        raise EvaluationError(msg)
    return tuple(dict.fromkeys(raw))  # type: ignore[return-value]


async def arun_replay_experiment(
    *,
    settings: Settings,
    arms: Sequence[str] | None = None,
    variants: Sequence[CaseVariant] = ("full", "spill"),
    cases: int | None = None,
    repetitions: int | None = None,
    out: Path | str | None = None,
    concurrency: int = 1,
    deps: ReplayDependencies | None = None,
    run_id: str | None = None,
) -> ReplayRun:
    """Run the chat-replay experiment asynchronously."""
    resolved = deps or build_replay_dependencies(settings)
    selected = select_arms(
        settings, list(arms) if arms else list(REPLAY_ARMS)
    )
    runner = ChatReplayRunner(resolved)
    return await runner.run(
        arms=selected,
        variants=list(variants),
        repetitions=repetitions or settings.evaluation.repetitions,
        cases=cases or settings.evaluation.max_cases,
        concurrency=concurrency,
        run_id=run_id,
        out=Path(out) if out is not None else Path(settings.evaluation.reports_dir),
    )


def run_replay_experiment(
    *,
    settings: Settings,
    arms: Sequence[str] | None = None,
    variants: Sequence[CaseVariant] = ("full", "spill"),
    cases: int | None = None,
    repetitions: int | None = None,
    out: Path | str | None = None,
    concurrency: int = 1,
    deps: ReplayDependencies | None = None,
    run_id: str | None = None,
) -> ReplayRun:
    """Synchronous wrapper used by the CLI."""
    return asyncio.run(
        arun_replay_experiment(
            settings=settings,
            arms=arms,
            variants=variants,
            cases=cases,
            repetitions=repetitions,
            out=out,
            concurrency=concurrency,
            deps=deps,
            run_id=run_id,
        )
    )


def main(
    *,
    settings: Settings,
    arms: Sequence[str] | None = None,
    variants: Sequence[CaseVariant] = ("full", "spill"),
    cases: int | None = None,
    repetitions: int | None = None,
    out: Path | str | None = None,
    concurrency: int = 1,
    run_id: str | None = None,
) -> int:
    """Entry point for the replay evaluation. Returns a process exit code."""
    run = run_replay_experiment(
        settings=settings,
        arms=arms,
        variants=variants,
        cases=cases,
        repetitions=repetitions,
        out=out,
        concurrency=concurrency,
        run_id=run_id,
    )
    for aggregate in run.report.arms:
        record: dict[str, Any] = aggregate.as_record()
        print(
            f"{record['arm']:<36} {record['variant']:<6} "
            f"retention={record['mean_retention']:.2f} "
            f"pass^k={record['pass_k']:.2f} prompt_tok={record['mean_prompt_tokens']:,.0f} "
            f"aux_tok={record['mean_aux_tokens']:,.0f} "
            f"spill_reads={record['mean_spill_reads']:.1f} "
            f"cost=${record['mean_cost_usd']:.4f}/trial "
            f"overflow={record['overflow_rate']:.0%} errors={record['error_rate']:.0%}"
        )
    print(f"total cost: ${run.report.total_cost.as_float():.4f}")
    if run.directory is not None:
        print(f"report: {run.directory / 'report.md'}")
    return 0


__all__ = [
    "REPLAY_ARMS",
    "ChatReplayRunner",
    "ReplayDependencies",
    "ReplayRun",
    "arun_replay_experiment",
    "build_replay_dependencies",
    "main",
    "resolve_variants",
    "run_replay_experiment",
]
