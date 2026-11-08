#!/usr/bin/env python3
"""Read one experiment report and print the tables Chapter 4 uses.

The runner writes machine-readable results; the thesis needs a readable
comparison plus the spread across repetitions, because a mean without its
variance is not a measurement. This script never calls a model and never writes
anything: it reads ``.reports/evals/<run_id>/results.json`` and prints.

Usage:
    python scripts/summarize_experiment.py                      # newest run
    python scripts/summarize_experiment.py --run chapter4-main
    python scripts/summarize_experiment.py --json               # machine-readable
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORTS = ROOT / ".reports" / "evals"
RESULTS_FILENAME = "results.json"

ARM_ORDER = (
    "baseline_full_history",
    "baseline_capped",
    "sliding_window",
    "message_selection",
    "message_selection_decision",
    "message_selection_decision_plus_truncation",
    "anchored_compaction",
    "tool_truncation_only",
    "sliding_window_plus_truncation",
    "message_selection_plus_truncation",
    "anchored_compaction_plus_truncation",
)


def newest_run(directory: Path) -> Path:
    """The most recently written run directory."""
    candidates = sorted(
        (item for item in directory.iterdir() if (item / RESULTS_FILENAME).is_file()),
        key=lambda item: (item / RESULTS_FILENAME).stat().st_mtime,
    )
    if not candidates:
        msg = f"no experiment report under {directory}"
        raise FileNotFoundError(msg)
    return candidates[-1]


def load(run_dir: Path) -> dict[str, Any]:
    payload = json.loads((run_dir / RESULTS_FILENAME).read_text(encoding="utf-8"))
    if "run" not in payload or "trials" not in payload:
        msg = f"{run_dir / RESULTS_FILENAME} is not an experiment report"
        raise ValueError(msg)
    return payload


def group(trials: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Trials per arm, in the canonical arm order."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trial in trials:
        grouped.setdefault(trial["arm"], []).append(trial)
    ordered = {name: grouped[name] for name in ARM_ORDER if name in grouped}
    ordered.update({name: value for name, value in grouped.items() if name not in ordered})
    return ordered


def spread(values: list[float]) -> str:
    """Mean and standard deviation, or a dash for a single value."""
    if not values:
        return "-"
    mean = statistics.fmean(values)
    if len(values) < 2:
        return f"{mean:.2f}"
    return f"{mean:.2f} ± {statistics.stdev(values):.2f}"


def per_case_retention(arm_trials: list[dict[str, Any]]) -> dict[str, list[float]]:
    by_case: dict[str, list[float]] = {}
    for trial in arm_trials:
        by_case.setdefault(trial["case_id"], []).append(trial["retention"])
    return by_case


def cost_per_fact(arm_trials: list[dict[str, Any]]) -> str:
    """Dollars per correctly retained fact: what accuracy actually costs.

    A cheap arm that forgets everything is not a win, and an expensive arm that
    remembers everything may not be worth it. This is the ratio the thesis argues
    about, and it is only comparable because every arm answers the same probes.
    """
    correct = sum(trial["correct"] for trial in arm_trials)
    spent = sum(trial["cost_usd"] for trial in arm_trials)
    if correct == 0:
        return "-"
    return f"{spent / correct:.4f}"


def print_tables(payload: dict[str, Any]) -> None:
    run = payload["run"]
    trials = payload["trials"]
    grouped = group(trials)

    print(f"experiment {run['run_id']} · dataset {run['dataset']} · model {run['model']}")
    print(
        f"window {run['window_tokens']:,} tokens · repetitions {run['repetitions']} · "
        f"trials {len(trials)} · total ${run['total_cost_usd']:.4f}"
    )
    print()
    header = (
        f"{'arm':<40} {'retention':<12} {'pass^k':>7} {'prompt tok':>11} {'aux tok':>9} "
        f"{'cache':>7} {'$/trial':>9} {'$/fact':>8} {'overflow':>9} {'errors':>7}"
    )
    print(header)
    print("-" * len(header))
    for arm in run["arms"]:
        arm_trials = grouped.get(arm["arm"], [])
        retentions = [trial["retention"] for trial in arm_trials]
        print(
            f"{arm['arm']:<40} {spread(retentions):<12} {arm['pass_k']:>7.2f} "
            f"{arm.get('mean_prompt_tokens', arm['mean_input_tokens']):>11,.0f} "
            f"{arm.get('mean_aux_tokens', 0):>9,.0f} {arm['cache_hit_ratio']:>7.1%} "
            f"{arm['mean_cost_usd']:>9.4f} {cost_per_fact(arm_trials):>8} "
            f"{arm['overflow_rate']:>9.0%} {arm['error_rate']:>7.0%}"
        )

    print()
    print("retention by fact position (mean over repetitions)")
    position_header = f"{'arm':<40} {'early':>7} {'middle':>7} {'late':>7}"
    print(position_header)
    print("-" * len(position_header))
    for arm in run["arms"]:
        by_position = arm.get("retention_by_position", {})
        print(
            f"{arm['arm']:<36} {by_position.get('early', 0.0):>7.2f} "
            f"{by_position.get('middle', 0.0):>7.2f} {by_position.get('late', 0.0):>7.2f}"
        )

    print()
    print("per-case retention (repetitions of the same case)")
    case_ids = sorted({trial["case_id"] for trial in trials})
    case_header = f"{'arm':<40} " + " ".join(f"{case[-14:]:>14}" for case in case_ids)
    print(case_header)
    print("-" * len(case_header))
    for arm in run["arms"]:
        by_case = per_case_retention(grouped.get(arm["arm"], []))
        cells = " ".join(
            f"{statistics.fmean(by_case[case]):>14.2f}" if case in by_case else f"{'-':>14}"
            for case in case_ids
        )
        print(f"{arm['arm']:<40} {cells}")

    failures = [trial for trial in trials if trial.get("error")]
    if failures:
        print()
        print(f"trials with an error: {len(failures)}")
        reasons: dict[str, int] = {}
        for trial in failures:
            key = str(trial["error"]).split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
            print(f"  {count:>3} · {reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", help="run id (directory under the reports dir)")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS))
    parser.add_argument("--json", action="store_true", help="print the aggregated records as JSON")
    args = parser.parse_args(argv)

    reports = Path(args.reports_dir)
    run_dir = reports / args.run if args.run else newest_run(reports)
    payload = load(run_dir)

    if args.json:
        print(json.dumps({"run": payload["run"], "arms": payload["run"]["arms"]}, indent=2))
        return 0
    print_tables(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
