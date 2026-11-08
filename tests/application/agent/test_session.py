"""Session value objects: snapshots and the run result record."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from caio_code.application.agent.session import AgentRunResult, ContextSnapshot
from caio_code.domain.conversation.budget import TokenBudget
from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.domain.policy.base import PolicyDecision, PolicyPipeline, PolicyRequest
from caio_code.domain.policy.full_history import FullHistoryPolicy
from caio_code.domain.todo.items import TodoBoard
from caio_code.domain.usage.accounting import CacheStats, Cost, RunAccounting, TokenUsage
from caio_code.infrastructure.tokens.counter import CharProxyTokenCounter


def _transcript() -> Transcript:
    return Transcript.of(
        (
            Message(id="m1", role=Role.USER, text="do the thing"),
            Message(id="m2", role=Role.ASSISTANT, text="done"),
        )
    )


def _decision() -> PolicyDecision:
    counter = CharProxyTokenCounter()
    request = PolicyRequest(
        transcript=_transcript(), budget=TokenBudget(1_000), counter=counter
    )
    return FullHistoryPolicy().plan(request)


def test_snapshot_from_single_decision() -> None:
    snapshot = ContextSnapshot.from_decision(_decision())
    assert snapshot.policy == "baseline_full_history"
    assert snapshot.kept == 2
    assert snapshot.dropped == 0
    assert snapshot.budget_tokens == 1_000
    record = snapshot.as_record()
    for key in (
        "policy",
        "tokens_before",
        "tokens_after",
        "budget_tokens",
        "overflow_tokens",
        "kept",
        "dropped",
    ):
        assert key in record


def test_snapshot_from_pipeline_decision() -> None:
    counter = CharProxyTokenCounter()
    pipeline = PolicyPipeline("baseline_arm", [FullHistoryPolicy()])
    request = PolicyRequest(
        transcript=_transcript(), budget=TokenBudget(1_000), counter=counter
    )
    snapshot = ContextSnapshot.from_decision(pipeline.plan(request))
    assert snapshot.policy == "baseline_arm"
    assert snapshot.as_record()["pipeline"] == "baseline_arm"


def _result(**overrides: object) -> AgentRunResult:
    base: dict[str, object] = {
        "run_id": "run-1",
        "status": "completed",
        "final_text": "answer",
        "accounting": RunAccounting(
            usage=TokenUsage(input_tokens=10, output_tokens=4),
            cache=CacheStats.from_usages([TokenUsage(input_tokens=10, output_tokens=4)]),
            cost=Cost.zero(),
            model="stub",
        ),
        "board": TodoBoard(),
        "compactions": 0,
        "latency_ms": 250,
        "started_at": datetime(2026, 1, 1, tzinfo=UTC),
        "finished_at": datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        "context": ContextSnapshot.from_decision(_decision()),
    }
    base.update(overrides)
    return AgentRunResult(**base)  # type: ignore[arg-type]


def test_run_result_record_is_json_serializable() -> None:
    record = _result().as_record()
    text = json.dumps(record, default=str)
    assert json.loads(text)["status"] == "completed"
    assert record["usage"]["input_tokens"] == 10
    assert record["context"]["policy"] == "baseline_full_history"


def test_run_result_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="unknown run status 'exploded'"):
        _result(status="exploded")
