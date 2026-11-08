"""The driver report: what ran, what passed, what the screen said."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STEP_PASSED = "passed"
STEP_FAILED = "failed"
STEP_ERROR = "error"
REPORT_JSON_NAME = "report.json"


@dataclass(frozen=True, slots=True)
class StepRecord:
    """Outcome of one step, with the screen text right after it ran."""

    index: int
    description: str
    status: str
    elapsed_ms: int
    screen_text: str


@dataclass(slots=True)
class DriverReport:
    """Everything a human or an agent needs to judge a scenario run."""

    scenario: str
    size: tuple[int, int]
    steps: list[StepRecord] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    text_log: str = ""

    @property
    def passed(self) -> bool:
        return not self.failures

    def step_statuses(self) -> list[str]:
        return [step.status for step in self.steps]


def report_to_dict(report: DriverReport) -> dict[str, object]:
    """JSON-serializable form: the report schema another agent can parse."""
    data = asdict(report)
    data["passed"] = report.passed
    data["size"] = {"cols": report.size[0], "rows": report.size[1]}
    return data


def write_json(report: DriverReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_to_dict(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def as_markdown(report: DriverReport) -> str:
    """Readable outcome: summary, per-step table, failures, artifacts, log."""
    verdict = "PASSED" if report.passed else "FAILED"
    lines = [
        f"# driver report: {report.scenario} - {verdict}",
        "",
        f"- terminal size: {report.size[0]}x{report.size[1]}",
        f"- steps: {len(report.steps)}",
        f"- failed assertions: {len(report.failures)}",
        "",
        "## steps",
        "",
        "| # | step | status | elapsed ms |",
        "|---|------|--------|-----------:|",
    ]
    for step in report.steps:
        lines.append(f"| {step.index} | {step.description} | {step.status} | {step.elapsed_ms} |")
    if report.failures:
        lines += ["", "## failures", ""]
        lines += [f"- {failure}" for failure in report.failures]
    if report.screenshots:
        lines += ["", "## artifacts", ""]
        lines += [f"- `{path}`" for path in report.screenshots]
    lines += ["", "## screen text log", "", "```text", report.text_log.rstrip("\n"), "```", ""]
    return "\n".join(lines)
