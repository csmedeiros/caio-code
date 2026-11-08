"""Scoring one trial and aggregating one arm.

Accuracy alone would hide the point of the thesis: a policy that answers well
by spending four times the tokens is not a win. Every trial therefore carries
its retention, its token cost, its cache behaviour and its price, and the
aggregate reports pass^k over repetitions rather than a single lucky run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from caio_code.domain.usage.accounting import CacheStats, Cost, TokenUsage


@dataclass(frozen=True, slots=True)
class ProbeScore:
    """Outcome of one probe in one trial."""

    probe_id: str
    fact_id: str
    position: str
    correct: bool
    answer: str
    expected: str


@dataclass(frozen=True, slots=True)
class TrialResult:
    """One case, one arm, one repetition."""

    trial_id: str
    case_id: str
    arm: str
    repetition: int
    probes: tuple[ProbeScore, ...]
    usage: TokenUsage
    cache: CacheStats
    cost: Cost
    model: str
    variant: str = "full"
    """Case variant: ``full`` recorded outputs, or ``spill`` truncated-to-file outputs."""
    probe_usage: TokenUsage = field(default_factory=TokenUsage)
    """What the agent model itself was sent: the shaped context plus the probes."""

    aux_usage: TokenUsage = field(default_factory=TokenUsage)
    """What the arm spent to shape and grade that context: summarizer, decision-model
    and judge calls. Never summed into ``probe_usage``."""
    replay: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
    """Chat-replay evidence: tool-server stats, the judge's verdicts, the agent reply."""
    latency_ms: int = 0
    messages_in: int = 0
    messages_after_policy: int = 0
    tokens_before_policy: int = 0
    tokens_after_policy: int = 0
    budget_tokens: int = 0
    overflow_tokens: int = 0
    compactions: int = 0
    truncated_tool_outputs: int = 0
    error: str | None = None
    policy_record: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def correct(self) -> int:
        return sum(1 for probe in self.probes if probe.correct)

    @property
    def total_probes(self) -> int:
        return len(self.probes)

    @property
    def retention(self) -> float:
        """Fraction of critical facts the agent still knew, in [0, 1]."""
        if not self.probes:
            return 0.0
        return self.correct / self.total_probes

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.probes and self.correct == self.total_probes

    @property
    def aux_cost_share(self) -> float:
        """Fraction of the bill paid to shaping rather than answering, in [0, 1]."""
        if self.cost.usd <= 0:
            return 0.0
        prompt = self.probe_usage.input_tokens
        total = self.usage.input_tokens
        if total <= 0:
            return 0.0
        return 1.0 - (prompt / total)

    @property
    def cache_hit_ratio(self) -> float:
        return self.cache.hit_ratio

    @property
    def tokens_saved(self) -> int:
        return max(0, self.tokens_before_policy - self.tokens_after_policy)

    def as_record(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "case_id": self.case_id,
            "arm": self.arm,
            "repetition": self.repetition,
            "variant": self.variant,
            "model": self.model,
            "retention": round(self.retention, 4),
            "correct": self.correct,
            "total_probes": self.total_probes,
            "succeeded": self.succeeded,
            "error": self.error,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "cached_input_tokens": self.usage.cached_input_tokens,
                "total_tokens": self.usage.total_tokens,
            },
            "probe_usage": {
                "input_tokens": self.probe_usage.input_tokens,
                "output_tokens": self.probe_usage.output_tokens,
                "cached_input_tokens": self.probe_usage.cached_input_tokens,
            },
            "aux_usage": {
                "input_tokens": self.aux_usage.input_tokens,
                "output_tokens": self.aux_usage.output_tokens,
            },
            "cache": {
                "calls": self.cache.calls,
                "hit_ratio": round(self.cache.hit_ratio, 6),
                "call_hit_ratio": round(self.cache.call_hit_ratio, 6),
            },
            "cost_usd": self.cost.as_float(),
            "latency_ms": self.latency_ms,
            "messages_in": self.messages_in,
            "messages_after_policy": self.messages_after_policy,
            "tokens_before_policy": self.tokens_before_policy,
            "tokens_after_policy": self.tokens_after_policy,
            "budget_tokens": self.budget_tokens,
            "overflow_tokens": self.overflow_tokens,
            "tokens_saved": self.tokens_saved,
            "compactions": self.compactions,
            "truncated_tool_outputs": self.truncated_tool_outputs,
            "probes": [
                {
                    "probe_id": probe.probe_id,
                    "fact_id": probe.fact_id,
                    "position": probe.position,
                    "correct": probe.correct,
                    "answer": probe.answer,
                    "expected": probe.expected,
                }
                for probe in self.probes
            ],
            "policy": self.policy_record,
            "replay": self.replay,
        }


def pass_at_k(trials: Sequence[TrialResult], k: int) -> float:
    """pass^k as the probability that all ``k`` repetitions of a case succeed.

    Reported instead of pass@1 because an agent that succeeds once in three is
    not an agent a team can use: consistency is part of the claim.
    """
    if k <= 0:
        msg = f"k must be positive, got {k}"
        raise ValueError(msg)
    by_case: dict[str, list[bool]] = {}
    for trial in trials:
        by_case.setdefault(trial.case_id, []).append(trial.succeeded)
    if not by_case:
        return 0.0
    consistent = 0
    for outcomes in by_case.values():
        window = outcomes[:k]
        if len(window) >= k and all(window):
            consistent += 1
    return consistent / len(by_case)


@dataclass(frozen=True, slots=True)
class ArmAggregate:
    """One policy arm, aggregated over cases and repetitions."""

    arm: str
    model: str
    trials: tuple[TrialResult, ...]
    repetitions: int
    variant: str = "all"
    """Case variant this aggregate covers; ``all`` when the run had a single variant."""

    @property
    def case_count(self) -> int:
        return len({trial.case_id for trial in self.trials})

    @property
    def mean_retention(self) -> float:
        if not self.trials:
            return 0.0
        return sum(trial.retention for trial in self.trials) / len(self.trials)

    @property
    def success_rate(self) -> float:
        if not self.trials:
            return 0.0
        return sum(1 for trial in self.trials if trial.succeeded) / len(self.trials)

    @property
    def pass_k(self) -> float:
        return pass_at_k(self.trials, self.repetitions)

    @property
    def total_cost(self) -> Cost:
        total = Cost.zero()
        for trial in self.trials:
            total = total + trial.cost
        return total

    @property
    def mean_cost(self) -> Cost:
        if not self.trials:
            return Cost.zero()
        return Cost(self.total_cost.usd / len(self.trials))

    @property
    def total_usage(self) -> TokenUsage:
        total = TokenUsage()
        for trial in self.trials:
            total = total + trial.usage
        return total

    @property
    def mean_input_tokens(self) -> float:
        """Every token the arm spent, agent-facing and auxiliary together."""
        if not self.trials:
            return 0.0
        return sum(trial.usage.input_tokens for trial in self.trials) / len(self.trials)

    @property
    def mean_prompt_tokens(self) -> float:
        """Tokens the agent model was actually sent: the shaped context.

        This is the column arms are compared on. Auxiliary calls are excluded
        here and reported next to it, because a summarizer that reads 25k tokens
        to save 30k is a different claim from a policy that simply sends less.

        A trial that never reached the agent counts as zero, not as its auxiliary
        bill: substituting the total would charge the failed call's scorer tokens
        to the prompt column and inflate the very number being compared.
        """
        if not self.trials:
            return 0.0
        counted = [trial.probe_usage.input_tokens for trial in self.trials]
        return sum(counted) / len(counted)

    @property
    def mean_aux_tokens(self) -> float:
        if not self.trials:
            return 0.0
        return sum(trial.aux_usage.input_tokens for trial in self.trials) / len(self.trials)

    @property
    def cache_hit_ratio(self) -> float:
        return CacheStats.from_usages(trial.usage for trial in self.trials).hit_ratio

    def _mean_replay_stat(self, key: str) -> float:
        if not self.trials:
            return 0.0
        values = [
            trial.replay.get("tools", {}).get(key, 0) for trial in self.trials
        ]
        return sum(values) / len(values)

    @property
    def mean_spill_reads(self) -> float:
        """How often the agent read a spilled output back during probing."""
        return self._mean_replay_stat("spill_reads")

    @property
    def mean_tool_calls(self) -> float:
        return self._mean_replay_stat("calls")

    @property
    def mean_tool_misses(self) -> float:
        return self._mean_replay_stat("misses")

    @property
    def mean_latency_ms(self) -> float:
        if not self.trials:
            return 0.0
        return sum(trial.latency_ms for trial in self.trials) / len(self.trials)

    @property
    def overflow_rate(self) -> float:
        if not self.trials:
            return 0.0
        return sum(1 for trial in self.trials if trial.overflow_tokens > 0) / len(self.trials)

    @property
    def error_rate(self) -> float:
        if not self.trials:
            return 0.0
        return sum(1 for trial in self.trials if trial.error is not None) / len(self.trials)

    def retention_by_position(self) -> dict[str, float]:
        """Retention split by where the fact sat in the history: early/middle/late."""
        buckets: dict[str, list[bool]] = {}
        for trial in self.trials:
            for probe in trial.probes:
                buckets.setdefault(probe.position, []).append(probe.correct)
        return {
            position: (sum(outcomes) / len(outcomes) if outcomes else 0.0)
            for position, outcomes in sorted(buckets.items())
        }

    def as_record(self) -> dict[str, Any]:
        usage = self.total_usage
        return {
            "arm": self.arm,
            "variant": self.variant,
            "model": self.model,
            "trials": len(self.trials),
            "cases": self.case_count,
            "repetitions": self.repetitions,
            "mean_retention": round(self.mean_retention, 4),
            "success_rate": round(self.success_rate, 4),
            "pass_k": round(self.pass_k, 4),
            "retention_by_position": {
                position: round(value, 4)
                for position, value in self.retention_by_position().items()
            },
            "mean_prompt_tokens": round(self.mean_prompt_tokens, 1),
            "mean_aux_tokens": round(self.mean_aux_tokens, 1),
            "mean_input_tokens": round(self.mean_input_tokens, 1),
            "total_input_tokens": usage.input_tokens,
            "total_cached_input_tokens": usage.cached_input_tokens,
            "cache_hit_ratio": round(self.cache_hit_ratio, 6),
            "total_cost_usd": self.total_cost.as_float(),
            "mean_cost_usd": self.mean_cost.as_float(),
            "mean_latency_ms": round(self.mean_latency_ms, 1),
            "mean_tool_calls": round(self.mean_tool_calls, 2),
            "mean_spill_reads": round(self.mean_spill_reads, 2),
            "mean_tool_misses": round(self.mean_tool_misses, 2),
            "overflow_rate": round(self.overflow_rate, 4),
            "error_rate": round(self.error_rate, 4),
        }


@dataclass(frozen=True, slots=True)
class ExperimentReport:
    """The whole experiment: every arm, the dataset, and the run metadata."""

    run_id: str
    dataset: str
    model: str
    arms: tuple[ArmAggregate, ...]
    window_tokens: int
    repetitions: int
    seed: int
    started_at: str
    finished_at: str
    total_cost: Cost

    def as_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset": self.dataset,
            "model": self.model,
            "window_tokens": self.window_tokens,
            "repetitions": self.repetitions,
            "seed": self.seed,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_cost_usd": self.total_cost.as_float(),
            "arms": [arm.as_record() for arm in self.arms],
        }
