"""Offline end-to-end tests of the chat-replay evaluation.

The scripted agent answers from keyword routing; the ``StubJudgeGateway``
grades by substring match, so retention here measures the harness plumbing,
not a model. The point of the suite: seed -> shape once -> probe in-band ->
judge, with the spill variant recoverable through the replay tool server.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caio_code.application.evaluation.judge import PAYLOAD_PLACEHOLDER, LlmJudge
from caio_code.application.evaluation.replay import (
    REPLAY_ARMS,
    ChatReplayRunner,
    ReplayDependencies,
    resolve_variants,
)
from caio_code.application.evaluation.replay_tools import READ_FILE_TOOL
from caio_code.application.experiment.arms import select_arms
from caio_code.config import (
    CompactionConfig,
    EvalConfig,
    Settings,
    ToolOutputConfig,
    WindowConfig,
)
from caio_code.domain.conversation.messages import Message, Role, ToolCall
from caio_code.domain.errors import EvaluationError
from caio_code.domain.evaluation.cases import (
    CriticalFact,
    EvalDataset,
    HistoryCase,
    Probe,
)
from caio_code.domain.evaluation.spill import spill_path
from caio_code.domain.usage.accounting import PriceSheet
from caio_code.infrastructure.llm.stub import (
    StubGateway,
    StubJudgeGateway,
    StubScorer,
    StubSummarizer,
)
from caio_code.infrastructure.observability.clocks import FixedClock, SequentialIdentifiers
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter

START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_TOKENS = 60
BIG_MAX_BYTES = 200
COUNTER = CharProxyTokenCounter()
BLOCK = "lorem ipsum dolor sit amet " * 8  # ~26 proxy tokens per filler message
BIG_OUTPUT = "test log\n" * 60 + "the port is 9142\n"  # above BIG_MAX_BYTES -> spills
PROBE_KEYWORD = "answer these questions"
JUDGE_TEMPLATE = "Grade each item.\n\n" + PAYLOAD_PLACEHOLDER


def _make_case(case_id: str = "c1") -> HistoryCase:
    """Two facts: one early in the pinned task, one late inside a big tool output."""
    messages = [
        Message(
            id=f"{case_id}-task",
            role=Role.USER,
            text=f"Task {case_id}: the token is zephyr-token",
            pinned=True,
        ),
        Message(
            id=f"{case_id}-m1",
            role=Role.ASSISTANT,
            text="running the suite",
            tool_calls=(
                ToolCall(id=f"{case_id}-tc1", name="run_tests", arguments='{"suite": "pay"}'),
            ),
        ),
        Message(
            id=f"{case_id}-m2",
            role=Role.TOOL,
            text=BIG_OUTPUT,
            tool_call_id=f"{case_id}-tc1",
            name="run_tests",
        ),
    ]
    messages.extend(
        Message(id=f"{case_id}-f{i}", role=Role.ASSISTANT, text=BLOCK) for i in range(8)
    )
    facts = (
        CriticalFact(
            id=f"{case_id}-fact1",
            statement="the token",
            answer="zephyr-token",
            position="early",
        ),
        CriticalFact(
            id=f"{case_id}-fact2",
            statement="the port",
            answer="9142",
            position="late",
        ),
    )
    probes = (
        Probe(
            id=f"{case_id}-p1",
            fact_id=f"{case_id}-fact1",
            question="What is the token?",
            expected="zephyr-token",
        ),
        Probe(
            id=f"{case_id}-p2",
            fact_id=f"{case_id}-fact2",
            question="What is the port?",
            expected="9142",
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


CASE = _make_case()
DATASET = EvalDataset(name="tiny-replay", cases=(CASE,))
CORRECT_ANSWER = "The token is zephyr-token and the port is 9142."
READ_SPILL_CALL = ToolCall(
    id="tc-read",
    name=READ_FILE_TOOL,
    arguments=json.dumps({"path": spill_path(CASE.id, f"{CASE.id}-m2")}),
)


def _settings(*, cap: int = 3, window: int = WINDOW_TOKENS) -> Settings:
    return Settings(
        window=WindowConfig(tokens=window),
        compaction=CompactionConfig(keep_tokens=window),
        tool_output=ToolOutputConfig(max_bytes=BIG_MAX_BYTES),
        evaluation=EvalConfig(probe_tool_call_cap=cap),
    )


def _judge(*replies: str) -> LlmJudge:
    gateway = (
        StubJudgeGateway(clock=FixedClock(START))
        if not replies
        else StubGateway(clock=FixedClock(START), replies=list(replies))
    )
    return LlmJudge(gateway=gateway, prompt_template=JUDGE_TEMPLATE)


def _deps(
    gateway: StubGateway,
    *,
    judge: LlmJudge | None = None,
    settings: Settings | None = None,
    dataset: EvalDataset = DATASET,
) -> ReplayDependencies:
    return ReplayDependencies(
        settings=settings or _settings(),
        dataset=dataset,
        counter=COUNTER,
        gateway=gateway,
        judge=judge or _judge(),
        pricing=PriceSheet(),
        clock=FixedClock(START),
        identifiers=SequentialIdentifiers(prefix="replay"),
        summarizer=StubSummarizer(clock=FixedClock(START)),
        scorer=StubScorer(),
    )


def _answering_gateway() -> StubGateway:
    return StubGateway(
        clock=FixedClock(START), keyword_replies={PROBE_KEYWORD: CORRECT_ANSWER}
    )


async def test_probe_round_answers_in_band_and_the_judge_grades() -> None:
    deps = _deps(_answering_gateway())
    runner = ChatReplayRunner(deps)
    (arm,) = select_arms(deps.settings, ["sliding_window"])

    trial = await runner.run_trial(arm, CASE, "full", 1)

    assert trial.error is None
    assert trial.variant == "full"
    assert trial.retention == 1.0
    assert [probe.correct for probe in trial.probes] == [True, True]
    assert trial.replay["agent_reply"] == CORRECT_ANSWER
    assert trial.replay["judge"]["verdicts"][0]["correct"] is True
    # accounting split: the agent call is prompt, the judge call is aux
    assert trial.probe_usage.input_tokens > 0
    assert trial.aux_usage.input_tokens > 0


async def test_scripted_agent_reads_the_spilled_file_and_recovers_the_fact() -> None:
    gateway = StubGateway(
        clock=FixedClock(START),
        keyword_replies={PROBE_KEYWORD: CORRECT_ANSWER},
        keyword_tool_calls={PROBE_KEYWORD: (READ_SPILL_CALL,)},
    )
    deps = _deps(gateway)
    runner = ChatReplayRunner(deps)
    (arm,) = select_arms(deps.settings, ["sliding_window"])

    trial = await runner.run_trial(arm, CASE, "spill", 1)

    assert trial.error is None
    assert trial.variant == "spill"
    tools = trial.replay["tools"]
    assert tools["spill_reads"] == 1
    assert tools["calls"] == 1
    assert tools["misses"] == 0
    # the fact lived only inside the spilled output; reading it back recovered it
    assert trial.retention == 1.0


async def test_tool_calls_stop_at_the_probe_cap() -> None:
    gateway = StubGateway(
        clock=FixedClock(START),
        keyword_replies={PROBE_KEYWORD: CORRECT_ANSWER},
        keyword_tool_calls={
            "token": (READ_SPILL_CALL,),
            "port": (READ_SPILL_CALL,),
        },
    )
    deps = _deps(gateway, settings=_settings(cap=1))
    runner = ChatReplayRunner(deps)
    (arm,) = select_arms(deps.settings, ["sliding_window"])

    trial = await runner.run_trial(arm, CASE, "spill", 1)

    assert trial.error is None
    assert trial.replay["tools"]["calls"] == 1


async def test_unmatched_tool_call_is_a_counted_visible_miss() -> None:
    # nome gravado, argumentos inéditos: passa no filtro de superfície do stub e
    # ainda assim é um miss do servidor de replay
    miss_call = ToolCall(id="tc-again", name="run_tests", arguments='{"suite": "other"}')
    gateway = StubGateway(
        clock=FixedClock(START),
        keyword_replies={PROBE_KEYWORD: CORRECT_ANSWER},
        keyword_tool_calls={PROBE_KEYWORD: (miss_call,)},
    )
    deps = _deps(gateway)
    runner = ChatReplayRunner(deps)
    (arm,) = select_arms(deps.settings, ["sliding_window"])

    trial = await runner.run_trial(arm, CASE, "full", 1)

    tools = trial.replay["tools"]
    assert tools["misses"] == 1
    assert tools["outcomes"][0]["error"] == "ToolUnavailableInReplay"


async def test_baseline_keeps_the_overflow_visible_and_still_probes() -> None:
    deps = _deps(_answering_gateway())
    runner = ChatReplayRunner(deps)
    (arm,) = select_arms(deps.settings, ["baseline_full_history"])

    trial = await runner.run_trial(arm, CASE, "full", 1)

    assert trial.error is None  # overflow is a result, not a failure, for this arm
    assert trial.overflow_tokens > 0
    assert trial.tokens_after_policy > trial.budget_tokens
    assert trial.retention == 1.0


async def test_compaction_arm_summarizes_once_with_an_assistant_summary() -> None:
    deps = _deps(_answering_gateway())
    runner = ChatReplayRunner(deps)
    (arm,) = select_arms(deps.settings, ["anchored_compaction"])

    trial = await runner.run_trial(arm, CASE, "full", 1)

    assert trial.error is None
    assert trial.compactions == 1
    assert trial.aux_usage.input_tokens > 0  # the summarizer call is aux, not prompt


async def test_judge_failure_is_recorded_not_swallowed() -> None:
    deps = _deps(_answering_gateway(), judge=_judge("I cannot grade this."))
    runner = ChatReplayRunner(deps)
    (arm,) = select_arms(deps.settings, ["sliding_window"])

    trial = await runner.run_trial(arm, CASE, "full", 1)

    assert trial.error is not None
    assert "judge error" in trial.error
    assert trial.retention == 0.0


async def test_run_refuses_a_case_that_does_not_overflow_the_window() -> None:
    deps = _deps(_answering_gateway(), settings=_settings(window=100_000))
    runner = ChatReplayRunner(deps)
    arms = select_arms(deps.settings, list(REPLAY_ARMS))

    with pytest.raises(EvaluationError, match="does not overflow"):
        await runner.run(arms=arms, variants=["full"], repetitions=1)


async def test_run_aggregates_per_arm_and_variant_and_writes_the_reports(
    tmp_path: Path,
) -> None:
    deps = _deps(_answering_gateway())
    runner = ChatReplayRunner(deps)
    arms = select_arms(deps.settings, ["sliding_window", "baseline_full_history"])

    run = await runner.run(
        arms=arms,
        variants=["full", "spill"],
        repetitions=1,
        run_id="replay-test",
        out=tmp_path,
    )

    assert len(run.trials) == 4
    assert {(a.arm, a.variant) for a in run.report.arms} == {
        ("sliding_window", "full"),
        ("sliding_window", "spill"),
        ("baseline_full_history", "full"),
        ("baseline_full_history", "spill"),
    }
    directory = tmp_path / "replay-test"
    assert (directory / "results.json").is_file()
    report = (directory / "report.md").read_text(encoding="utf-8")
    comparison = (directory / "report-comparison.md").read_text(encoding="utf-8")
    assert "| Cache hit |" not in report  # no cache column: not measurable in replay
    assert "| Variant |" in report
    assert "Retention delta (spill - full)" in comparison

    payload = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    variants = {trial["variant"] for trial in payload["trials"]}
    assert variants == {"full", "spill"}
    assert all("replay" in trial for trial in payload["trials"])


def test_resolve_variants_deduplicates_and_rejects_unknown_names() -> None:
    assert resolve_variants(None) == ("full",)
    assert resolve_variants(("spill", "full", "spill")) == ("spill", "full")
    with pytest.raises(EvaluationError, match="unknown variants"):
        resolve_variants(("truncated",))
