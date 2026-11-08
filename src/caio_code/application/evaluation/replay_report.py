"""Replay-run reports: the variant column in, the cache column out.

Same two artifacts as the v4 experiment report (``results.json`` is the
evidence Chapter 4 cites), plus ``report-comparison.md`` contrasting ``full``
against ``spill`` per arm -- the truncation factor is a column, never averaged
away. The cache-hit column is deliberately absent: a replayed history cannot
honestly measure a provider prompt cache, and printing a number the design
cannot back would be worse than printing none. The threat-to-validity note in
the paper says so.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from caio_code.domain.errors import StorageError
from caio_code.domain.evaluation.scoring import ArmAggregate, ExperimentReport, TrialResult

RESULTS_FILENAME = "results.json"
REPORT_FILENAME = "report.md"
COMPARISON_FILENAME = "report-comparison.md"

REPLAY_TABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("arm", "Arm", "{value}"),
    ("variant", "Variant", "{value}"),
    ("mean_retention", "Retention", "{value:.2f}"),
    ("pass_k", "pass^k", "{value:.2f}"),
    ("success_rate", "All probes", "{value:.2f}"),
    ("mean_prompt_tokens", "Prompt tok", "{value:,.0f}"),
    ("mean_aux_tokens", "Aux tok", "{value:,.0f}"),
    ("mean_tool_calls", "Tool calls", "{value:.1f}"),
    ("mean_spill_reads", "Spill reads", "{value:.1f}"),
    ("mean_tool_misses", "Tool misses", "{value:.1f}"),
    ("mean_cost_usd", "Cost/trial", "${value:.4f}"),
    ("total_cost_usd", "Total cost", "${value:.4f}"),
    ("overflow_rate", "Overflow", "{value:.0%}"),
    ("error_rate", "Errors", "{value:.0%}"),
    ("mean_latency_ms", "Latency ms", "{value:,.0f}"),
)

COMPARISON_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("variant", "Variant", "{value}"),
    ("mean_retention", "Retention", "{value:.2f}"),
    ("mean_prompt_tokens", "Prompt tok", "{value:,.0f}"),
    ("mean_aux_tokens", "Aux tok", "{value:,.0f}"),
    ("mean_tool_calls", "Tool calls", "{value:.1f}"),
    ("mean_spill_reads", "Spill reads", "{value:.1f}"),
    ("mean_cost_usd", "Cost/trial", "${value:.4f}"),
    ("error_rate", "Errors", "{value:.0%}"),
)


def write_replay_report(
    report: ExperimentReport, trials: Sequence[TrialResult], directory: Path
) -> Path:
    """Write results.json, report.md and report-comparison.md; return the directory."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"cannot create report directory {directory}: {exc}"
        raise StorageError(msg) from exc

    payload = {
        "run": report.as_record(),
        "trials": [trial.as_record() for trial in trials],
    }
    try:
        (directory / RESULTS_FILENAME).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (directory / REPORT_FILENAME).write_text(
            as_markdown(report, trials), encoding="utf-8"
        )
        (directory / COMPARISON_FILENAME).write_text(
            as_comparison_markdown(report), encoding="utf-8"
        )
    except OSError as exc:
        msg = f"cannot write the replay report into {directory}: {exc}"
        raise StorageError(msg) from exc
    return directory


def as_markdown(report: ExperimentReport, trials: Sequence[TrialResult]) -> str:
    """The arm x variant comparison table plus per-position retention."""
    lines: list[str] = [
        f"# Chat-replay evaluation {report.run_id}",
        "",
        f"- Dataset: `{report.dataset}` ({len({t.case_id for t in trials})} cases)",
        f"- Model: `{report.model}`",
        f"- Declared window: {report.window_tokens:,} tokens",
        f"- Repetitions per case: {report.repetitions} (pass^k uses all of them)",
        f"- Seed: {report.seed}",
        f"- Started: {report.started_at} - finished: {report.finished_at}",
        f"- Total cost: ${report.total_cost.as_float():.4f}",
        f"- Trials: {len(trials)}",
        "- Cache hit is **not reported**: a replayed history cannot measure a",
        "  provider prompt cache honestly (see threats to validity).",
        "",
        "## Arms x variants",
        "",
        _table([arm.as_record() for arm in report.arms], REPLAY_TABLE_COLUMNS),
        "",
        "## Retention by fact position",
        "",
        _position_table(report.arms),
        "",
        "## Errors",
        "",
    ]
    lines.extend(_trial_notes(trials))
    return "\n".join(lines) + "\n"


def as_comparison_markdown(report: ExperimentReport) -> str:
    """Per arm: full vs spill, and the retention/cost delta between them."""
    lines: list[str] = [
        f"# Truncation vs retention {report.run_id}",
        "",
        "Does spilling oversized tool outputs to files change what the agent",
        "retains after its context is shaped? Same histories, same probes;",
        "`spill` replaces tool outputs above the byte cap with a pointer the",
        "agent can read back during probing.",
        "",
    ]
    by_arm: dict[str, dict[str, ArmAggregate]] = {}
    for aggregate in report.arms:
        by_arm.setdefault(aggregate.arm, {})[aggregate.variant] = aggregate

    for arm_name, variants in by_arm.items():
        lines.extend([f"## {arm_name}", "", _table(
            [agg.as_record() for _, agg in sorted(variants.items())],
            COMPARISON_COLUMNS,
        ), ""])
        full = variants.get("full")
        spill = variants.get("spill")
        if full is not None and spill is not None:
            retention_delta = spill.mean_retention - full.mean_retention
            prompt_delta = spill.mean_prompt_tokens - full.mean_prompt_tokens
            cost_delta = spill.mean_cost.as_float() - full.mean_cost.as_float()
            lines.extend([
                f"- Retention delta (spill - full): {retention_delta:+.2f}",
                f"- Prompt tokens delta: {prompt_delta:+,.0f}",
                f"- Cost/trial delta: ${cost_delta:+.4f}",
                f"- Spill reads per trial: {spill.mean_spill_reads:.1f}",
                "",
            ])
    return "\n".join(lines) + "\n"


def _table(records: Sequence[dict[str, Any]], columns: Sequence[tuple[str, str, str]]) -> str:
    header = "| " + " | ".join(label for _, label, _ in columns) + " |"
    separator = "|" + "|".join("---" for _ in columns) + "|"
    rows: list[str] = []
    for record in records:
        cells: list[str] = []
        for key, _, template in columns:
            value = record.get(key)
            cells.append(template.format(value=value) if not isinstance(value, str) else value)
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, separator, *rows])


def _position_table(arms: Sequence[ArmAggregate]) -> str:
    positions = ("early", "middle", "late")
    header = (
        "| Arm | Variant | " + " | ".join(p.title() for p in positions) + " |"
    )
    separator = "|---" * (len(positions) + 2) + "|"
    rows: list[str] = []
    for arm in arms:
        breakdown = arm.retention_by_position()
        cells = [f"{breakdown.get(position, 0.0):.2f}" for position in positions]
        rows.append(f"| {arm.arm} | {arm.variant} | " + " | ".join(cells) + " |")
    return "\n".join([header, separator, *rows])


def _trial_notes(trials: Sequence[TrialResult]) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    for trial in trials:
        key = f"{trial.arm}:{trial.variant}"
        if key in seen or trial.error is None:
            continue
        seen.add(key)
        notes.append(f"- **{trial.arm}** ({trial.variant}): {trial.error}")
    if not notes:
        notes.append("- No trial reported an error.")
    return notes


__all__ = [
    "COMPARISON_FILENAME",
    "REPORT_FILENAME",
    "RESULTS_FILENAME",
    "as_comparison_markdown",
    "as_markdown",
    "write_replay_report",
]
