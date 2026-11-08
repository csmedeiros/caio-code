"""Offline tests for the experiment runner, answer parsing and pass^k scoring."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from caio_code.application.experiment.arms import select_arms
from caio_code.application.experiment.runner import (
    ExperimentDependencies,
    ExperimentRunner,
    _resolve_settings,
    parse_answers,
    score_answers,
)
from caio_code.config import CompactionConfig, ModelPrice, Settings, WindowConfig
from caio_code.domain.conversation.messages import Message, Role
from caio_code.domain.errors import ConfigurationError
from caio_code.domain.evaluation.cases import (
    CriticalFact,
    EvalDataset,
    HistoryCase,
    Probe,
)
from caio_code.domain.evaluation.scoring import (
    ArmAggregate,
    ProbeScore,
    TrialResult,
    pass_at_k,
)
from caio_code.domain.usage.accounting import CacheStats, Cost, PriceSheet, TokenUsage
from caio_code.infrastructure.llm.stub import StubGateway, StubScorer, StubSummarizer
from caio_code.infrastructure.observability.clocks import FixedClock, SequentialIdentifiers
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_TOKENS = 60
COUNTER = CharProxyTokenCounter()
BLOCK = "lorem ipsum dolor sit amet " * 8  # ~26 proxy tokens per filler message


def _make_case(case_id: str, early_answer: str, late_answer: str) -> HistoryCase:
    messages = [
        Message(
            id=f"{case_id}-task",
            role=Role.USER,
            text=f"Task {case_id}: the token is {early_answer}",
            pinned=True,
        )
    ]
    messages.extend(
        Message(id=f"{case_id}-m{i}", role=Role.ASSISTANT, text=BLOCK) for i in range(10)
    )
    messages.append(
        Message(
            id=f"{case_id}-final",
            role=Role.USER,
            text=f"Remember: the port is {late_answer}",
        )
    )
    facts = (
        CriticalFact(
            id=f"{case_id}-f1",
            statement="the token",
            answer=early_answer,
            position="early",
        ),
        CriticalFact(
            id=f"{case_id}-f2",
            statement="the port",
            answer=late_answer,
            position="late",
        ),
    )
    probes = (
        Probe(
            id=f"{case_id}-p1",
            fact_id=f"{case_id}-f1",
            question="What is the token?",
            expected=early_answer,
        ),
        Probe(
            id=f"{case_id}-p2",
            question="What is the port?",
            fact_id=f"{case_id}-f2",
            expected=late_answer,
        ),
    )
    return HistoryCase(
        id=case_id,
        description=f"synthetic case {case_id}",
        messages=tuple(messages),
        facts=facts,
        probes=probes,
        task=f"keep the facts of {case_id}",
    )


CASE_ONE = _make_case("case-one", "zephyr-token", "9142")
CASE_TWO = _make_case("case-two", "quartz-token", "8033")
DATASET = EvalDataset(name="tiny-histories", cases=(CASE_ONE, CASE_TWO))

REPLIES = {
    "case-one": json.dumps({"answers": {"case-one-p1": "zephyr-token", "case-one-p2": "9142"}}),
    "case-two": json.dumps({"answers": {"case-two-p1": "unknown", "case-two-p2": "8033"}}),
}


class BillingScorer(StubScorer):
    """Scores like the stub, but hands over a bill, as a decision model would."""

    def __init__(self, *, bill: TokenUsage) -> None:
        super().__init__()
        self._bill = bill
        self.calls = 0

    async def ascore(self, *, task, messages):  # type: ignore[no-untyped-def,override]
        self.calls += 1
        return await super().ascore(task=task, messages=messages)

    def drain_usage(self) -> tuple[TokenUsage, ...]:
        return (self._bill,) if self.calls else ()


def _dependencies(
    gateway: StubGateway | None = None, decision_scorer: BillingScorer | None = None
) -> tuple[ExperimentDependencies, StubGateway]:
    settings = Settings(
        window=WindowConfig(tokens=WINDOW_TOKENS),
        compaction=CompactionConfig(keep_tokens=WINDOW_TOKENS),
    )
    resolved_gateway = gateway or StubGateway(clock=FixedClock(START), keyword_replies=REPLIES)
    deps = ExperimentDependencies(
        settings=settings,
        dataset=DATASET,
        counter=COUNTER,
        gateway=resolved_gateway,
        pricing=PriceSheet(),
        clock=FixedClock(START),
        identifiers=SequentialIdentifiers(prefix="exp"),
        summarizer=StubSummarizer(clock=FixedClock(START)),
        scorer=StubScorer(),
        decision_scorer=decision_scorer,
    )
    return deps, resolved_gateway


class CountingGateway(StubGateway):
    """StubGateway that also counts how many completions it served."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.calls = 0

    async def acomplete(self, messages, *, system=None, max_tokens=None, temperature=None):  # type: ignore[no-untyped-def,override]
        self.calls += 1
        return await super().acomplete(
            messages, system=system, max_tokens=max_tokens, temperature=temperature
        )


def _trial(case_id: str, *, succeeded: bool) -> TrialResult:
    probes = (
        ProbeScore(
            probe_id=f"{case_id}-p1",
            fact_id=f"{case_id}-f1",
            position="early",
            correct=succeeded,
            answer="a",
            expected="a",
        ),
    )
    return TrialResult(
        trial_id=f"t:{case_id}",
        case_id=case_id,
        arm="arm",
        repetition=1,
        probes=probes,
        usage=TokenUsage(input_tokens=10, output_tokens=2),
        cache=CacheStats.from_usages([TokenUsage(input_tokens=10, output_tokens=2)]),
        cost=Cost(Decimal("0.01")),
        model="stub",
    )


async def test_run_trial_retention_reflects_the_stub_answers() -> None:
    deps, _ = _dependencies()
    runner = ExperimentRunner(deps)
    (arm,) = select_arms(deps.settings, ["sliding_window"])

    full = await runner.run_trial(arm, CASE_ONE, 1)
    unknown = await runner.run_trial(arm, CASE_TWO, 1)

    assert full.error is None
    assert full.retention == 1.0
    assert [probe.correct for probe in full.probes] == [True, True]
    assert unknown.retention == 0.5
    assert unknown.probes[0].correct is False  # "unknown" is never correct
    assert unknown.probes[1].correct is True


async def test_enforce_window_overflow_records_an_error_trial_without_calling_the_gateway() -> None:
    gateway = CountingGateway(clock=FixedClock(START), keyword_replies=REPLIES)
    deps, _ = _dependencies(gateway=gateway)
    runner = ExperimentRunner(deps)
    (arm,) = select_arms(deps.settings, ["baseline_capped"])

    trial = await runner.run_trial(arm, CASE_ONE, 1)

    assert trial.error is not None
    assert "overflow" in trial.error
    assert trial.retention == 0.0
    assert gateway.calls == 0


async def test_compaction_arm_calls_the_summarizer_once_and_bills_it_to_the_trial() -> None:
    deps, _ = _dependencies()
    runner = ExperimentRunner(deps)
    (arm,) = select_arms(deps.settings, ["anchored_compaction"])

    trial = await runner.run_trial(arm, CASE_ONE, 1)

    assert trial.compactions == 1
    assert trial.error is None
    # The trial usage is the probe call plus the summarizer call; the probe call
    # alone cannot exceed the pre-policy transcript plus the system prompt.
    probe_only_ceiling = trial.tokens_before_policy + COUNTER.count_text(
        json.dumps({"answers": {"case-one-p1": "zephyr-token", "case-one-p2": "9142"}})
    )
    assert trial.usage.input_tokens > probe_only_ceiling


async def test_decision_arm_bills_the_scorer_as_auxiliary_and_not_as_prompt() -> None:
    scorer = BillingScorer(bill=TokenUsage(input_tokens=500, output_tokens=40))
    deps, _ = _dependencies(decision_scorer=scorer)
    # "stub" is priced at zero on purpose, so the billing test needs a real price.
    deps = replace(
        deps,
        pricing=PriceSheet(prices=(ModelPrice("stub", Decimal("1.00"), Decimal("0.50"), Decimal("3.00")),)),
    )
    runner = ExperimentRunner(deps)
    (arm,) = select_arms(deps.settings, ["message_selection_decision"])

    trial = await runner.run_trial(arm, CASE_ONE, 1)

    assert trial.error is None
    assert scorer.calls == 1
    assert trial.aux_usage.input_tokens == 500
    assert trial.probe_usage.input_tokens == trial.usage.input_tokens - 500
    recorded = trial.policy_record["scorer"]
    assert recorded["kind"] == "decision"
    assert recorded["input_tokens"] == 500
    assert recorded["cost_usd"] > 0
    assert trial.cost.as_float() > Cost(Decimal("0")).as_float()


async def test_lexical_arm_reports_no_auxiliary_usage() -> None:
    scorer = BillingScorer(bill=TokenUsage(input_tokens=500))
    deps, _ = _dependencies(decision_scorer=scorer)
    runner = ExperimentRunner(deps)
    (arm,) = select_arms(deps.settings, ["message_selection"])

    trial = await runner.run_trial(arm, CASE_ONE, 1)

    assert scorer.calls == 0  # the lexical arm never reaches for the decision model
    assert trial.aux_usage.input_tokens == 0
    assert trial.probe_usage.input_tokens == trial.usage.input_tokens


def test_arm_aggregate_separates_prompt_tokens_from_auxiliary_tokens() -> None:
    trials = (
        TrialResult(
            trial_id="t1",
            case_id="c1",
            arm="decision",
            repetition=1,
            probes=(),
            usage=TokenUsage(input_tokens=1_200, output_tokens=10),
            cache=CacheStats.from_usages([TokenUsage(input_tokens=1_200)]),
            cost=Cost(Decimal("0.02")),
            model="stub",
            probe_usage=TokenUsage(input_tokens=1_000, output_tokens=10),
            aux_usage=TokenUsage(input_tokens=200),
        ),
        TrialResult(
            trial_id="t2",
            case_id="c2",
            arm="decision",
            repetition=1,
            probes=(),
            usage=TokenUsage(input_tokens=800, output_tokens=5),
            cache=CacheStats.from_usages([TokenUsage(input_tokens=800)]),
            cost=Cost(Decimal("0.01")),
            model="stub",
            probe_usage=TokenUsage(input_tokens=400, output_tokens=5),
            aux_usage=TokenUsage(input_tokens=400),
        ),
    )
    aggregate = ArmAggregate(arm="decision", model="stub", trials=trials, repetitions=1)

    assert aggregate.mean_prompt_tokens == 700.0  # what the agent saw
    assert aggregate.mean_aux_tokens == 300.0  # what shaping cost
    assert aggregate.mean_input_tokens == 1_000.0  # the two together
    record = aggregate.as_record()
    assert record["mean_prompt_tokens"] == 700.0
    assert record["mean_aux_tokens"] == 300.0


def test_failed_trial_does_not_push_its_auxiliary_bill_into_the_prompt_column() -> None:
    scored = TrialResult(
        trial_id="t1",
        case_id="c1",
        arm="decision",
        repetition=1,
        probes=(),
        usage=TokenUsage(input_tokens=44_000, output_tokens=100),
        cache=CacheStats(),
        cost=Cost(Decimal("0.05")),
        model="stub",
        probe_usage=TokenUsage(input_tokens=8_000, output_tokens=100),
        aux_usage=TokenUsage(input_tokens=36_000),
    )
    failed = TrialResult(
        trial_id="t2",
        case_id="c2",
        arm="decision",
        repetition=1,
        probes=(),
        usage=TokenUsage(input_tokens=36_000),
        cache=CacheStats(),
        cost=Cost(Decimal("0.04")),
        model="stub",
        error="provider error: APITimeoutError",
        aux_usage=TokenUsage(input_tokens=36_000),
    )
    aggregate = ArmAggregate(arm="decision", model="stub", trials=(scored, failed), repetitions=1)

    assert aggregate.mean_prompt_tokens == 4_000.0  # (8_000 + 0) / 2, never 36k
    assert aggregate.mean_aux_tokens == 36_000.0


def test_aux_cost_share_is_zero_without_auxiliary_tokens() -> None:
    trial = TrialResult(
        trial_id="t1",
        case_id="c1",
        arm="plain",
        repetition=1,
        probes=(),
        usage=TokenUsage(input_tokens=100, output_tokens=5),
        cache=CacheStats(),
        cost=Cost(Decimal("0.01")),
        model="stub",
        probe_usage=TokenUsage(input_tokens=100, output_tokens=5),
    )

    assert trial.aux_cost_share == 0.0


def test_parse_answers_handles_clean_json() -> None:
    assert parse_answers('{"answers": {"p1": "42"}}') == {"p1": "42"}


def test_parse_answers_handles_json_wrapped_in_prose() -> None:
    text = 'Sure! Here you go: {"answers": {"p1": "42"}} — hope that helps.'

    assert parse_answers(text) == {"p1": "42"}


def test_parse_answers_handles_fenced_json() -> None:
    text = '```json\n{"answers": {"p1": "42"}}\n```'

    assert parse_answers(text) == {"p1": "42"}


def test_parse_answers_handles_answer_lines() -> None:
    text = "p1: 42\np2 = the answer"

    assert parse_answers(text) == {"p1": "42", "p2": "the answer"}


def test_parse_answers_of_garbage_is_empty() -> None:
    assert parse_answers("!!! ??? ---") == {}


def test_score_answers_accepts_only_probe_acceptable_answers() -> None:
    reply = json.dumps({"answers": {"p1": "eight thousand", "p2": "nope"}})
    probes = (
        Probe(id="p1", fact_id="f1", question="q?", expected="8000", aliases=("eight thousand",)),
        Probe(id="p2", fact_id="f2", question="q?", expected="9000"),
    )

    scored = score_answers(reply, probes, positions={"f1": "early", "f2": "late"})

    assert [item.correct for item in scored] == [True, False]
    assert scored[0].position == "early"


def test_score_answers_treats_unknown_as_wrong() -> None:
    probes = (Probe(id="p1", fact_id="f1", question="q?", expected="8000"),)

    scored = score_answers(json.dumps({"answers": {"p1": "unknown"}}), probes)

    assert scored[0].correct is False


def test_pass_at_k_is_one_when_every_repetition_succeeded() -> None:
    trials = [_trial("c1", succeeded=True), _trial("c1", succeeded=True)]

    assert pass_at_k(trials, 2) == 1.0


def test_pass_at_k_is_zero_when_one_repetition_failed() -> None:
    trials = [_trial("c1", succeeded=True), _trial("c1", succeeded=False)]

    assert pass_at_k(trials, 2) == 0.0


def test_pass_at_k_raises_for_k_below_one() -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        pass_at_k([_trial("c1", succeeded=True)], 0)


async def test_run_aggregates_arms_and_writes_both_artifacts(tmp_path: Path) -> None:
    deps, _ = _dependencies()
    runner = ExperimentRunner(deps)
    arms = select_arms(deps.settings, ["sliding_window", "anchored_compaction"])

    run = await runner.run(
        arms=arms, repetitions=2, cases=1, concurrency=2, run_id="run-42", out=tmp_path
    )

    assert len(run.trials) == 4  # 2 arms x 1 case x 2 repetitions
    assert {aggregate.arm for aggregate in run.report.arms} == {arm.name for arm in arms}
    directory = tmp_path / "run-42"
    payload = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    assert payload["run"]["run_id"] == "run-42"
    assert len(payload["trials"]) == len(run.trials)
    markdown = (directory / "report.md").read_text(encoding="utf-8")
    for arm in arms:
        assert f"| {arm.name} |" in markdown
    assert run.directory == directory


async def test_run_respects_the_case_limit(tmp_path: Path) -> None:
    deps, _ = _dependencies()
    runner = ExperimentRunner(deps)
    (arm,) = select_arms(deps.settings, ["sliding_window"])

    run = await runner.run(arms=[arm], repetitions=1, cases=1, out=tmp_path)

    assert {trial.case_id for trial in run.trials} == {"case-one"}


def test_retention_by_position_has_the_three_documented_keys() -> None:
    def probe(position: str, correct: bool) -> ProbeScore:
        return ProbeScore(
            probe_id=f"p-{position}",
            fact_id=f"f-{position}",
            position=position,
            correct=correct,
            answer="a",
            expected="a",
        )

    trial = TrialResult(
        trial_id="t:positions",
        case_id="c1",
        arm="arm",
        repetition=1,
        probes=(probe("early", True), probe("middle", False), probe("late", True)),
        usage=TokenUsage(),
        cache=CacheStats(),
        cost=Cost.zero(),
        model="stub",
    )

    aggregate = ArmAggregate(arm="arm", model="stub", trials=(trial,), repetitions=1)
    breakdown = aggregate.retention_by_position()

    assert set(breakdown) == {"early", "middle", "late"}
    assert breakdown == {"early": 1.0, "middle": 0.0, "late": 1.0}


def test_cost_arithmetic_stays_in_decimal() -> None:
    trials = tuple(_trial(f"c{i}", succeeded=True) for i in range(3))

    aggregate = ArmAggregate(arm="arm", model="stub", trials=trials, repetitions=1)

    assert isinstance(aggregate.total_cost.usd, Decimal)
    assert isinstance(aggregate.mean_cost.usd, Decimal)
    assert aggregate.total_cost.usd == aggregate.mean_cost.usd * len(trials)
    assert abs(aggregate.mean_cost.as_float() * 3 - aggregate.total_cost.as_float()) < 0.01


def test_resolve_settings_reports_an_explicit_window_that_disagrees_with_settings() -> None:
    # `settings or load_settings(...)` descartava window_tokens sempre que o
    # chamador também passava settings -- e a CLI sempre passa. Um run pedido
    # com janela de 32k era moldado e julgado contra 8k, em silêncio.
    settings = Settings(
        window=WindowConfig(tokens=WINDOW_TOKENS),
        compaction=CompactionConfig(keep_tokens=WINDOW_TOKENS),
    )

    with pytest.raises(ConfigurationError, match="window_tokens"):
        _resolve_settings(settings, window_tokens=WINDOW_TOKENS * 4)


def test_resolve_settings_accepts_an_explicit_window_that_agrees_with_settings() -> None:
    settings = Settings(
        window=WindowConfig(tokens=WINDOW_TOKENS),
        compaction=CompactionConfig(keep_tokens=WINDOW_TOKENS),
    )

    assert _resolve_settings(settings, window_tokens=WINDOW_TOKENS) is settings


def test_resolve_settings_applies_the_declared_window_when_no_settings_are_passed() -> None:
    resolved = _resolve_settings(None, provider="stub", window_tokens=32_000)

    assert resolved.window.tokens == 32_000
