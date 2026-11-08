"""Experiment reports: JSON for the record, Markdown for the thesis.

Two artifacts per run, written next to each other:

``<run_id>/results.json``
    every trial, one object per line of the ``trials`` array, plus the arm
    aggregates and the run metadata. This is the evidence Chapter 4 cites.
``<run_id>/report.md``
    the comparison table, readable without a notebook.
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

TABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("arm", "Arm", "{value}"),
    ("mean_retention", "Retention", "{value:.2f}"),
    ("pass_k", "pass^k", "{value:.2f}"),
    ("success_rate", "All probes", "{value:.2f}"),
    ("mean_prompt_tokens", "Prompt tok", "{value:,.0f}"),
    ("mean_aux_tokens", "Aux tok", "{value:,.0f}"),
    ("cache_hit_ratio", "Cache hit", "{value:.1%}"),
    ("mean_cost_usd", "Cost/trial", "${value:.4f}"),
    ("total_cost_usd", "Total cost", "${value:.4f}"),
    ("overflow_rate", "Overflow", "{value:.0%}"),
    ("error_rate", "Errors", "{value:.0%}"),
    ("mean_latency_ms", "Latency ms", "{value:,.0f}"),
)


def write_report(report: ExperimentReport, trials: Sequence[TrialResult], directory: Path) -> Path:
    """Write both artifacts and return the directory they live in."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        msg = f"cannot create report directory {directory}: {exc}"
        raise StorageError(msg) from exc

    payload = {
        "run": report.as_record(),
        "trials": [trial.as_record() for trial in trials],
    }
    results_path = directory / RESULTS_FILENAME
    try:
        results_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (directory / REPORT_FILENAME).write_text(as_markdown(report, trials), encoding="utf-8")
    except OSError as exc:
        msg = f"cannot write the experiment report into {directory}: {exc}"
        raise StorageError(msg) from exc
    return directory


def as_markdown(report: ExperimentReport, trials: Sequence[TrialResult]) -> str:
    """The comparison table plus the per-position retention breakdown."""
    lines: list[str] = [
        f"# Context-policy experiment {report.run_id}",
        "",
        f"- Dataset: `{report.dataset}` ({len({t.case_id for t in trials})} cases)",
        f"- Model: `{report.model}`",
        f"- Declared window: {report.window_tokens:,} tokens",
        f"- Repetitions per case: {report.repetitions} (pass^k uses all of them)",
        f"- Seed: {report.seed}",
        f"- Started: {report.started_at} - finished: {report.finished_at}",
        f"- Total cost: ${report.total_cost.as_float():.4f}",
        f"- Trials: {len(trials)}",
        "",
        "## Arms",
        "",
        _table([arm.as_record() for arm in report.arms]),
        "",
        "## Retention by fact position",
        "",
        _position_table(report.arms),
        "",
        "## Arm descriptions",
        "",
    ]
    lines.extend(_trial_notes(trials))
    return "\n".join(lines) + "\n"


def _table(records: Sequence[dict[str, Any]]) -> str:
    header = "| " + " | ".join(label for _, label, _ in TABLE_COLUMNS) + " |"
    separator = "|" + "|".join("---" for _ in TABLE_COLUMNS) + "|"
    rows: list[str] = []
    for record in records:
        cells: list[str] = []
        for key, _, template in TABLE_COLUMNS:
            value = record.get(key)
            cells.append(template.format(value=value) if not isinstance(value, str) else value)
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join([header, separator, *rows])


def _position_table(arms: Sequence[ArmAggregate]) -> str:
    positions = ("early", "middle", "late")
    header = "| Arm | " + " | ".join(position.title() for position in positions) + " |"
    separator = "|---" * (len(positions) + 1) + "|"
    rows: list[str] = []
    for arm in arms:
        breakdown = arm.retention_by_position()
        cells = [f"{breakdown.get(position, 0.0):.2f}" for position in positions]
        rows.append(f"| {arm.arm} | " + " | ".join(cells) + " |")
    return "\n".join([header, separator, *rows])


def _trial_notes(trials: Sequence[TrialResult]) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    for trial in trials:
        if trial.arm in seen or trial.error is None:
            continue
        seen.add(trial.arm)
        notes.append(f"- **{trial.arm}**: {trial.error}")
    if not notes:
        notes.append("- No arm reported an error.")
    return notes


def report_to_dict(report: ExperimentReport, trials: Sequence[TrialResult]) -> dict[str, Any]:
    """The same payload ``write_report`` stores, without touching the disk."""
    return {"run": report.as_record(), "trials": [trial.as_record() for trial in trials]}


def summarize_arms(arms: Sequence[ArmAggregate]) -> list[dict[str, Any]]:
    """Plain records, handy for the CLI table and for the notebooks."""
    return [arm.as_record() for arm in arms]


__all__ = [
    "REPORT_FILENAME",
    "RESULTS_FILENAME",
    "as_markdown",
    "report_to_dict",
    "summarize_arms",
    "write_report",
]
