"""Offline tests for the LLM judge: prompt render, verdict parse, calibration."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from caio_code.application.evaluation.judge import (
    PAYLOAD_PLACEHOLDER,
    JudgeItem,
    LabeledAnswer,
    LlmJudge,
    judge_items_for,
    parse_verdicts,
    render_judge_prompt,
)
from caio_code.domain.errors import EvaluationError
from caio_code.domain.evaluation.cases import Probe
from caio_code.infrastructure.llm.stub import StubGateway
from caio_code.infrastructure.observability.clocks import FixedClock

START = datetime(2026, 1, 1, tzinfo=UTC)
TEMPLATE = (
    "Grade each item.\n\nItems to grade:\n\n" + PAYLOAD_PLACEHOLDER + "\n"
)


def _item(probe_id: str = "p1", *, reply: str = "the port is 9142") -> JudgeItem:
    return JudgeItem(
        probe_id=probe_id,
        question="What is the port?",
        gold_answer="9142",
        aliases=("port 9142",),
        agent_reply=reply,
    )


def _verdicts(*pairs: tuple[str, bool]) -> str:
    return json.dumps(
        {
            "verdicts": [
                {"probe_id": pid, "correct": ok, "reason": "r"} for pid, ok in pairs
            ]
        }
    )


def _judge(*replies: str) -> LlmJudge:
    gateway = StubGateway(clock=FixedClock(START), replies=list(replies))
    return LlmJudge(gateway=gateway, prompt_template=TEMPLATE)


def test_render_replaces_the_payload_placeholder() -> None:
    rendered = render_judge_prompt(TEMPLATE, [_item()])
    assert PAYLOAD_PLACEHOLDER not in rendered
    assert '"probe_id": "p1"' in rendered
    assert '"gold_answer": "9142"' in rendered


def test_render_refuses_a_template_without_the_placeholder() -> None:
    with pytest.raises(EvaluationError):
        render_judge_prompt("no placeholder here", [_item()])


def test_parse_accepts_bare_json_fenced_json_and_prose_around_json() -> None:
    payload = _verdicts(("p1", True))
    for text in (
        payload,
        f"```json\n{payload}\n```",
        f"Sure! Here you go: {payload} -- hope that helps.",
    ):
        (verdict,) = parse_verdicts(text, expected_ids=["p1"])
        assert verdict.probe_id == "p1"
        assert verdict.correct is True


def test_parse_orders_verdicts_by_expected_ids() -> None:
    text = _verdicts(("p2", False), ("p1", True))
    verdicts = parse_verdicts(text, expected_ids=["p1", "p2"])
    assert [v.probe_id for v in verdicts] == ["p1", "p2"]
    assert [v.correct for v in verdicts] == [True, False]


def test_missing_verdict_is_an_error_not_a_silent_incorrect() -> None:
    with pytest.raises(EvaluationError, match="no verdict"):
        parse_verdicts(_verdicts(("p1", True)), expected_ids=["p1", "p2"])


def test_unparseable_reply_is_an_error_naming_the_defect() -> None:
    with pytest.raises(EvaluationError):
        parse_verdicts("I cannot grade this.", expected_ids=["p1"])
    with pytest.raises(EvaluationError):
        parse_verdicts('{"verdicts": "not a list"}', expected_ids=["p1"])
    with pytest.raises(EvaluationError):
        parse_verdicts('{"verdicts": [{"probe_id": "p1"}]}', expected_ids=["p1"])


def test_judge_items_map_probes_to_payload_without_the_context() -> None:
    probes = (
        Probe(id="p1", fact_id="f1", question="port?", expected="9142", aliases=("x",)),
        Probe(id="p2", fact_id="f2", question="token?", expected="zephyr"),
    )
    items = judge_items_for(probes, "the port is 9142 and the token is zephyr")
    assert [item.probe_id for item in items] == ["p1", "p2"]
    assert items[0].aliases == ("x",)
    assert all(item.agent_reply.startswith("the port") for item in items)


async def test_agrade_grades_the_whole_round_in_one_call() -> None:
    judge = _judge(_verdicts(("p1", True), ("p2", False)))

    outcome = await judge.agrade([_item("p1"), _item("p2", reply="no idea")])

    assert [v.correct for v in outcome.verdicts] == [True, False]
    assert outcome.model == "stub"
    assert outcome.usage.input_tokens > 0


async def test_agrade_refuses_an_empty_round() -> None:
    with pytest.raises(EvaluationError):
        await _judge().agrade([])


async def test_calibration_counts_agreement_and_lists_disagreements() -> None:
    judge = _judge(
        _verdicts(("p1", True)),  # human: correct  -> agreement
        _verdicts(("p2", False)),  # human: correct -> disagreement
        _verdicts(("p3", False)),  # human: wrong   -> agreement
    )
    labeled = [
        LabeledAnswer(item=_item("p1"), human_correct=True),
        LabeledAnswer(item=_item("p2"), human_correct=True),
        LabeledAnswer(item=_item("p3", reply="guess?"), human_correct=False),
    ]

    report = await judge.acalibrate(labeled)

    assert report.total == 3
    assert report.agreements == 2
    assert report.agreement_ratio == pytest.approx(2 / 3)
    assert not report.passed(0.9)
    (disagreement,) = report.disagreements
    assert disagreement["probe_id"] == "p2"
    assert disagreement["human"] is True
    assert disagreement["judge"] is False


async def test_calibration_gate_passes_at_the_threshold() -> None:
    judge = _judge(*[_verdicts((f"p{i}", True)) for i in range(10)])
    labeled = [
        LabeledAnswer(item=_item(f"p{i}"), human_correct=True) for i in range(10)
    ]
    report = await judge.acalibrate(labeled)
    assert report.passed(0.9)
    assert report.as_record()["agreement_ratio"] == 1.0


async def test_calibration_needs_labels() -> None:
    with pytest.raises(EvaluationError):
        await _judge().acalibrate([])


def test_empty_template_is_refused() -> None:
    gateway = StubGateway(clock=FixedClock(START))
    with pytest.raises(EvaluationError):
        LlmJudge(gateway=gateway, prompt_template="   ")
