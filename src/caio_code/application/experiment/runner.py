"""The experiment: replay frozen long histories through every arm and score them.

One trial is: take a case's history, shape it with the arm's policy pipeline,
ask the model the case's probes over the shaped context, and score the answers
by alias match. The model never sees the unshaped history in a managed arm, and
never sees the probes before answering, so what is measured is exactly what a
policy leaves behind.

Everything a trial spends is accounted: the probe call and, in the compaction
arms, the summarizer call that produced the anchored summary. Cache hits come
from the provider's own usage counters, and cost is priced by the domain price
sheet, so "cheaper" in the report means dollars and not tokens.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from caio_code.application.compaction.service import CompactionService
from caio_code.application.experiment.arms import ArmSpec, select_arms
from caio_code.application.experiment.report import write_report
from caio_code.application.selection.service import SelectionService
from caio_code.config import Settings, load_settings
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.errors import ConfigurationError, ContextOverflowError, EvaluationError
from caio_code.domain.evaluation.cases import (
    EvalDataset,
    HistoryCase,
    Probe,
    answer_matches,
)
from caio_code.domain.evaluation.scoring import (
    ArmAggregate,
    ExperimentReport,
    ProbeScore,
    TrialResult,
)
from caio_code.domain.events import EventBus, InMemoryEventBus, RunFinished, RunStarted
from caio_code.domain.policy.base import PipelineDecision, PolicyPipeline, PolicyRequest
from caio_code.domain.policy.compaction import SUMMARY_PLACEHOLDER
from caio_code.domain.ports.gateway import ModelGateway, ModelReply
from caio_code.domain.ports.scorer import RelevanceScorer
from caio_code.domain.ports.summarizer import Summarizer
from caio_code.domain.ports.time import Clock, IdentifierFactory
from caio_code.domain.ports.tokenizer import TokenCounter
from caio_code.domain.usage.accounting import CacheStats, Cost, PriceSheet, TokenUsage

PROBE_SYSTEM_PROMPT = (
    "You are answering questions about a software engineering session whose earlier context may "
    "be summarized or trimmed. Answer only from the conversation given. Reply with a single JSON "
    'object of the form {"answers": {"<probe_id>": "<short exact answer>"}} and nothing else. '
    "Use the exact value, path, name or number that appears in the conversation; if the "
    'conversation does not contain it, answer "unknown".'
)
ANSWER_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_.:\-]+)\s*[:=]\s*(.+?)\s*$")
UNKNOWN_ANSWER = "unknown"


@dataclass(frozen=True, slots=True)
class ExperimentDependencies:
    """Everything the runner needs, injected."""

    settings: Settings
    dataset: EvalDataset
    counter: TokenCounter
    gateway: ModelGateway
    pricing: PriceSheet
    clock: Clock
    identifiers: IdentifierFactory
    bus: EventBus = field(default_factory=InMemoryEventBus)
    summarizer: Summarizer | None = None
    scorer: RelevanceScorer | None = None
    decision_scorer: RelevanceScorer | None = None
    """Scores relevance with the decision model, for the arms that ask for it."""

    decision_model: str = ""
    """Name of the decision model, so its tokens are priced as its own and not as the agent's.

    Pricing the scorer at the agent's rates would silently charge one vendor's bill to
    another's price list. With no published price the name falls through to
    ``FALLBACK_PRICE``, which is an estimate the report says is an estimate.
    """


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    """Outcome of one experiment: the report, the trials, and where they went."""

    report: ExperimentReport
    trials: tuple[TrialResult, ...]
    directory: Path | None


class ExperimentRunner:
    """Runs arms x cases x repetitions and aggregates the results."""

    def __init__(self, deps: ExperimentDependencies) -> None:
        self._deps = deps

    async def run(
        self,
        *,
        arms: Sequence[ArmSpec],
        repetitions: int,
        cases: int | None = None,
        concurrency: int = 1,
        run_id: str | None = None,
        out: Path | None = None,
    ) -> ExperimentRun:
        if repetitions < 1:
            msg = f"repetitions must be at least 1, got {repetitions}"
            raise EvaluationError(msg)
        if concurrency < 1:
            msg = f"concurrency must be at least 1, got {concurrency}"
            raise EvaluationError(msg)

        dataset = self._deps.dataset.limited(cases) if cases else self._deps.dataset
        resolved_run_id = run_id or self._deps.identifiers.run_id()
        started_at = self._deps.clock.now().isoformat()

        tasks = [
            (arm, case, repetition)
            for arm in arms
            for case in dataset.cases
            for repetition in range(1, repetitions + 1)
        ]
        semaphore = asyncio.Semaphore(concurrency)
        progress_dir = Path(out) / resolved_run_id if out is not None else None
        progress_path = _open_progress(progress_dir)
        completed = 0
        total = len(tasks)

        async def guarded(arm: ArmSpec, case: HistoryCase, repetition: int) -> TrialResult:
            nonlocal completed
            async with semaphore:
                trial = await self.run_trial(arm, case, repetition, run_id=resolved_run_id)
            completed += 1
            _record_progress(progress_path, trial, completed, total)
            return trial

        trials = list(await asyncio.gather(*(guarded(*task) for task in tasks)))
        _close_progress(progress_path)
        finished_at = self._deps.clock.now().isoformat()

        aggregates = tuple(
            ArmAggregate(
                arm=arm.name,
                model=self._deps.gateway.model,
                trials=tuple(trial for trial in trials if trial.arm == arm.name),
                repetitions=repetitions,
            )
            for arm in arms
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
            directory = write_report(report, trials, Path(out) / resolved_run_id)
        return ExperimentRun(report=report, trials=tuple(trials), directory=directory)

    async def run_trial(
        self,
        arm: ArmSpec,
        case: HistoryCase,
        repetition: int,
        *,
        run_id: str = "",
    ) -> TrialResult:
        """One shaped replay, its probes and its bill."""
        trial_id = f"{run_id or 'run'}:{arm.name}:{case.id}:{repetition}"
        started = self._deps.clock.monotonic_ms()
        self._deps.bus.publish(
            RunStarted(
                at=self._deps.clock.now(),
                run_id=trial_id,
                task=case.task,
                model=self._deps.gateway.model,
                policy=arm.name,
            )
        )

        pipeline = arm.pipeline(self._deps.settings)
        # Shaping and compaction are inside the same containment as the model
        # call: a summarizer timeout is a result of this arm, not a reason to
        # lose the other 130 trials of the experiment.
        try:
            request, scorer_usages = await self._build_request(arm, case, pipeline)
            transcript = request.transcript
            tokens_before = request.counter.count_transcript(transcript) + request.fixed_tokens
            decision = pipeline.plan(request)
            shaped, compaction_usage, compaction_cost, compactions = await self._apply_compaction(
                arm=arm,
                pipeline=pipeline,
                decision=decision,
                request=request,
                trial_id=trial_id,
            )
        except ContextOverflowError as exc:
            return self._failed_trial(
                trial_id, arm, case, repetition, started, str(exc), 0, _empty_request(case)
            )
        except Exception as exc:  # recorded as a trial error, never swallowed
            return self._failed_trial(
                trial_id,
                arm,
                case,
                repetition,
                started,
                f"{type(exc).__name__} while shaping the context: {exc}",
                0,
                _empty_request(case),
            )

        scorer_cost = _total_cost(
            self._deps.pricing,
            scorer_usages,
            self._deps.decision_model or self._deps.gateway.model,
        )

        # Re-measure after compaction: the planner's decision priced the summary as a
        # placeholder, and a real anchored summary costs up to summary_max_tokens.
        # Reporting the placeholder price would understate exactly the arm whose
        # overhead the thesis is about.
        tokens_after = request.counter.count_transcript(shaped) + request.fixed_tokens
        overflow_tokens = max(0, tokens_after - decision.budget_tokens)

        if arm.enforce_window and overflow_tokens > 0:
            error = (
                f"context overflow: the arm refuses to send {tokens_after} tokens "
                f"against a window of {decision.budget_tokens}"
            )
            trial = self._failed_trial(
                trial_id,
                arm,
                case,
                repetition,
                started,
                error,
                tokens_before,
                request,
                decision=decision,
                shaped=shaped,
                extra_usage=[*compaction_usage, *scorer_usages],
                extra_cost=compaction_cost + scorer_cost,
                compactions=compactions,
                tokens_after=tokens_after,
                overflow_tokens=overflow_tokens,
            )
            self._publish_finished(trial_id, trial)
            return trial

        messages = self._probe_messages(shaped, case)
        try:
            reply: ModelReply = await self._deps.gateway.acomplete(
                messages,
                system=PROBE_SYSTEM_PROMPT,
                temperature=0.0,
            )
        except Exception as exc:  # recorded as a trial error, never swallowed
            trial = self._failed_trial(
                trial_id,
                arm,
                case,
                repetition,
                started,
                f"provider error: {exc}",
                tokens_before,
                request,
                decision=decision,
                shaped=shaped,
                extra_usage=[*compaction_usage, *scorer_usages],
                extra_cost=compaction_cost + scorer_cost,
                compactions=compactions,
                tokens_after=tokens_after,
                overflow_tokens=overflow_tokens,
            )
            self._publish_finished(trial_id, trial)
            return trial

        probes = score_answers(
            reply.text,
            case.probes,
            positions={probe.fact_id: case.fact(probe.fact_id).position for probe in case.probes},
        )
        aux_usages = [*compaction_usage, *scorer_usages]
        usages = [reply.usage, *aux_usages]
        usage = _sum(usages)
        cost = (
            self._deps.pricing.cost_of(reply.usage, reply.model)
            + compaction_cost
            + scorer_cost
        )
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
            model=reply.model,
            probe_usage=reply.usage,
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
                    "input_tokens": sum(usage.input_tokens for usage in scorer_usages),
                    "output_tokens": sum(usage.output_tokens for usage in scorer_usages),
                    "cost_usd": scorer_cost.as_float(),
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
        transcript = case.transcript
        system_tokens = self._deps.counter.count_text(PROBE_SYSTEM_PROMPT) + self._deps.counter.count_text(
            case.task
        )
        request = PolicyRequest(
            transcript=transcript,
            budget=TokenBudget(arm.window_tokens),
            counter=self._deps.counter,
            fixed_tokens=system_tokens,
            task=case.task,
            tool_result_char_cap=settings.compaction.tool_result_char_cap,
        )
        if not arm.needs_scores:
            return request, []

        scorer = self._scorer_for(arm)
        threshold = (
            self._deps.settings.decision.relevance_threshold
            if arm.scorer_kind == "decision"
            else None
        )
        service = SelectionService(scorer, threshold=threshold)
        request = await service.with_scores(request, task=case.task)
        # The scorer's own bill belongs to the arm that used it: a judgement that
        # costs more than the tokens it saves is not a win, and hiding it in a
        # footnote would make the comparison unfair. `with_scores` already drained
        # the scorer, so the numbers are read from the outcome it recorded.
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
        pipeline: PolicyPipeline,
        decision: PipelineDecision,
        request: PolicyRequest,
        trial_id: str,
    ) -> tuple[Transcript, list[TokenUsage], Cost, int]:
        """Run the summarizer when the plan left a placeholder summary behind."""
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
            reason="experiment",
        )
        replaced = Transcript.of(
            outcome.message
            if SUMMARY_PLACEHOLDER in message.text
            else message
            for message in shaped
        )
        return replaced, [outcome.usage], outcome.cost, 1

    def _probe_messages(self, shaped: Transcript, case: HistoryCase) -> list[Message]:
        questions = "\n".join(
            f'- "{probe.id}": {probe.question}' for probe in case.probes
        )
        final = Message(
            id=f"{case.id}-probe",
            role=Role.USER,
            text=(
                f"Task of the session: {case.task}\n\n"
                "Answer these questions about the session above, using only what it contains:\n"
                f"{questions}\n\n"
                'Reply with JSON only: {"answers": {"<probe_id>": "<answer>"}}.'
            ),
            pinned=True,
        )
        return [*shaped.messages, final]

    def _failed_trial(
        self,
        trial_id: str,
        arm: ArmSpec,
        case: HistoryCase,
        repetition: int,
        started: int,
        error: str,
        tokens_before: int,
        request: PolicyRequest,
        *,
        decision: PipelineDecision | None = None,
        shaped: Transcript | None = None,
        extra_usage: Sequence[TokenUsage] = (),
        extra_cost: Cost | None = None,
        compactions: int = 0,
        tokens_after: int | None = None,
        overflow_tokens: int | None = None,
    ) -> TrialResult:
        usages = list(extra_usage)
        usage = _sum(usages)
        return TrialResult(
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
            aux_usage=usage,
            latency_ms=max(0, self._deps.clock.monotonic_ms() - started),
            messages_in=len(request.transcript),
            messages_after_policy=len(shaped) if shaped is not None else 0,
            tokens_before_policy=tokens_before,
            tokens_after_policy=(
                tokens_after
                if tokens_after is not None
                else (decision.tokens_after if decision else tokens_before)
            ),
            budget_tokens=decision.budget_tokens if decision else request.budget.tokens,
            overflow_tokens=(
                overflow_tokens
                if overflow_tokens is not None
                else (decision.overflow_tokens if decision else 0)
            ),
            compactions=compactions,
            truncated_tool_outputs=_truncation_count(decision) if decision else 0,
            error=error,
            policy_record=decision.as_record() if decision else {},
        )

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


# ---------------------------------------------------------------------------
# Scoring and helpers
# ---------------------------------------------------------------------------


def parse_answers(text: str) -> dict[str, str]:
    """Extract probe answers from a reply, tolerating prose around the JSON."""
    if not text.strip():
        return {}
    payload = _find_json(text)
    if payload is not None:
        answers = payload.get("answers", payload)
        if isinstance(answers, dict):
            return {
                str(key): _stringify(value)
                for key, value in answers.items()
                if _stringify(value).strip()
            }
    # Fallback: one "probe-id: answer" per line.
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        match = ANSWER_LINE_RE.match(line)
        if match:
            parsed[match.group(1)] = match.group(2).strip().strip("\"'")
    return parsed


def _find_json(text: str) -> dict[str, Any] | None:
    candidates: list[str] = []
    start = text.find("{")
    while start != -1:
        end = text.rfind("}")
        if end > start:
            candidates.append(text[start : end + 1])
        start = text.find("{", start + 1)
        if len(candidates) > 5:
            break
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def score_answers(
    reply: str,
    probes: Sequence[Probe],
    *,
    positions: dict[str, str] | None = None,
) -> tuple[ProbeScore, ...]:
    """Alias-match every probe against the reply."""
    answers = parse_answers(reply)
    scored: list[ProbeScore] = []
    for probe in probes:
        answer = answers.get(probe.id, "")
        if not answer:
            # A model that ignores the ids but answers in order still gets credit
            # when exactly one probe was asked.
            answer = reply if len(probes) == 1 else ""
        correct = bool(answer) and answer.strip().lower() != UNKNOWN_ANSWER and answer_matches(
            answer, probe.acceptable_answers
        )
        scored.append(
            ProbeScore(
                probe_id=probe.id,
                fact_id=probe.fact_id,
                position=(positions or {}).get(probe.fact_id, "middle"),
                correct=correct,
                answer=answer,
                expected=probe.expected,
            )
        )
    return tuple(scored)


def _empty_request(case: HistoryCase) -> PolicyRequest:
    """A request placeholder for trials that failed before shaping was measured."""
    from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

    return PolicyRequest(
        transcript=case.transcript,
        budget=TokenBudget(1),
        counter=CharProxyTokenCounter(),
    )


PROGRESS_FILENAME = "trials.jsonl"
"""One line per finished trial, flushed as it lands: a crash keeps the evidence."""


def _open_progress(directory: Path | None):
    """Open the incremental trial log, or return None when no output directory was given."""
    if directory is None:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    return (directory / PROGRESS_FILENAME).open("w", encoding="utf-8")


def _record_progress(handle, trial: TrialResult, completed: int, total: int) -> None:
    if handle is None:
        return
    record = trial.as_record()
    record["progress"] = f"{completed}/{total}"
    handle.write(json.dumps(record, sort_keys=True) + "\n")
    handle.flush()
    status = f"error: {trial.error}" if trial.error else f"retention {trial.retention:.2f}"
    print(
        f"[{completed:>3}/{total}] {trial.arm:<36} {trial.case_id:<34} "
        f"rep {trial.repetition} · {status} · {trial.usage.input_tokens:,} tok · "
        f"cache {trial.cache.hit_ratio:.0%} · ${trial.cost.as_float():.4f}",
        flush=True,
    )


def _close_progress(handle) -> None:
    if handle is not None:
        handle.close()


def _all_text(transcript: Transcript) -> str:
    return "\n".join(message.text for message in transcript)


def _total_cost(pricing: PriceSheet, usages: Sequence[TokenUsage], model: str) -> Cost:
    total = Cost.zero()
    for usage in usages:
        total = total + pricing.cost_of(usage, model)
    return total


def _sum(usages: Sequence[TokenUsage]) -> TokenUsage:
    total = TokenUsage()
    for usage in usages:
        total = total + usage
    return total


def _truncation_count(decision: PipelineDecision) -> int:
    return sum(
        len(step.decision.detail.get("truncated_messages", ())) for step in decision.steps
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def build_dependencies(
    settings: Settings,
    *,
    dataset: EvalDataset | None = None,
    bus: EventBus | None = None,
    clock: Clock | None = None,
    identifiers: IdentifierFactory | None = None,
    counter: TokenCounter | None = None,
    gateway: ModelGateway | None = None,
    summarizer: Summarizer | None = None,
    scorer: RelevanceScorer | None = None,
    pricing: PriceSheet | None = None,
) -> ExperimentDependencies:
    """Composition root for the experiment; every part is overridable for tests."""
    from caio_code.infrastructure.datasets.loader import load_dataset
    from caio_code.infrastructure.llm.factory import (
        build_gateway,
        build_scorer,
        build_summarizer,
    )
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
    from caio_code.infrastructure.decision.factory import build_decision_scorer
    from caio_code.infrastructure.llm.stub import StubScorer

    resolved_gateway = gateway or build_gateway(settings, clock=clock)
    lexical = StubScorer()
    resolved_scorer = scorer or build_scorer(settings, fallback=lexical, clock=clock)
    resolved_decision_scorer = build_decision_scorer(settings, fallback=lexical, clock=clock)
    decision_model = settings.decision.model if settings.decision.provider != "stub" else ""
    return ExperimentDependencies(
        settings=settings,
        dataset=dataset
        or load_dataset(Path(settings.evaluation.dataset_dir), limit=settings.evaluation.max_cases),
        counter=resolved_counter,
        gateway=resolved_gateway,
        pricing=pricing or pricing_for(settings),
        clock=clock or SystemClock(),
        identifiers=identifiers or SequentialIdentifiers(prefix="exp"),
        bus=bus or InMemoryEventBus(),
        summarizer=summarizer or build_summarizer(settings, clock=clock),
        scorer=resolved_scorer,
        decision_scorer=resolved_decision_scorer,
        decision_model=decision_model,
    )


async def arun_experiment(
    *,
    settings: Settings,
    arms: Sequence[str] | None = None,
    cases: int | None = None,
    repetitions: int | None = None,
    out: Path | str | None = None,
    concurrency: int = 1,
    deps: ExperimentDependencies | None = None,
    run_id: str | None = None,
) -> ExperimentRun:
    """Run the experiment asynchronously."""
    resolved = deps or build_dependencies(settings)
    selected = select_arms(settings, arms)
    runner = ExperimentRunner(resolved)
    return await runner.run(
        arms=selected,
        repetitions=repetitions or settings.evaluation.repetitions,
        cases=cases or settings.evaluation.max_cases,
        concurrency=concurrency,
        run_id=run_id,
        out=Path(out) if out is not None else Path(settings.evaluation.reports_dir),
    )


def run_experiment(
    *,
    settings: Settings,
    arms: Sequence[str] | None = None,
    cases: int | None = None,
    repetitions: int | None = None,
    out: Path | str | None = None,
    concurrency: int = 1,
    deps: ExperimentDependencies | None = None,
    run_id: str | None = None,
) -> ExperimentRun:
    """Synchronous wrapper used by the CLI and by the notebooks."""
    return asyncio.run(
        arun_experiment(
            settings=settings,
            arms=arms,
            cases=cases,
            repetitions=repetitions,
            out=out,
            concurrency=concurrency,
            deps=deps,
            run_id=run_id,
        )
    )


def _resolve_settings(
    settings: Settings | None,
    *,
    provider: str | None = None,
    model: str | None = None,
    window_tokens: int | None = None,
) -> Settings:
    """Settings for the run, with no explicit override silently dropped.

    ``settings or load_settings(...)`` discards ``window_tokens`` whenever a
    caller also passes settings -- and the CLI always does -- so the declared
    window stayed at its default: a run asked for 32,000 tokens was shaped and
    judged against 8,000. An override that disagrees with the settings it
    accompanies is a caller bug, so it is reported rather than discarded.
    """
    if settings is None:
        return load_settings(
            provider=provider, model=model, window_tokens=window_tokens
        )
    conflicts = [
        name
        for name, given, actual in (
            ("window_tokens", window_tokens, settings.window.tokens),
            ("model", model, settings.provider.model),
            ("provider", provider, settings.provider.provider),
        )
        if given is not None and given != actual
    ]
    if conflicts:
        msg = (
            "explicit overrides disagree with the settings passed in: "
            f"{', '.join(conflicts)}; pass settings or overrides, not both"
        )
        raise ConfigurationError(msg)
    return settings


def main(
    *,
    settings: Settings | None = None,
    arms: Sequence[str] | None = None,
    cases: int | None = None,
    repetitions: int | None = None,
    out: Path | str | None = None,
    concurrency: int = 1,
    provider: str | None = None,
    model: str | None = None,
    window_tokens: int | None = None,
    run_id: str | None = None,
) -> int:
    """Entry point for ``caio-code evaluate``. Returns a process exit code."""
    resolved = _resolve_settings(
        settings, provider=provider, model=model, window_tokens=window_tokens
    )
    run = run_experiment(
        settings=resolved,
        arms=arms,
        cases=cases,
        repetitions=repetitions,
        out=out,
        concurrency=concurrency,
        run_id=run_id,
    )
    for aggregate in run.report.arms:
        record = aggregate.as_record()
        print(
            f"{record['arm']:<42} retention={record['mean_retention']:.2f} "
            f"pass^k={record['pass_k']:.2f} prompt_tok={record['mean_prompt_tokens']:,.0f} "
            f"aux_tok={record['mean_aux_tokens']:,.0f} "
            f"cache={record['cache_hit_ratio']:.1%} cost=${record['mean_cost_usd']:.4f}/trial "
            f"overflow={record['overflow_rate']:.0%} errors={record['error_rate']:.0%}"
        )
    print(f"total cost: ${run.report.total_cost.as_float():.4f}")
    if run.directory is not None:
        print(f"report: {run.directory / 'report.md'}")
    return 0


__all__ = [
    "ExperimentDependencies",
    "ExperimentRun",
    "ExperimentRunner",
    "arun_experiment",
    "build_dependencies",
    "main",
    "parse_answers",
    "run_experiment",
    "score_answers",
]
