"""DriverReport serialization: JSON schema and Markdown rendering."""

from __future__ import annotations

import json

import pytest

from caio_code.presentation.tui.driver.report import (
    STEP_FAILED,
    STEP_PASSED,
    DriverReport,
    StepRecord,
    as_markdown,
    report_to_dict,
    write_json,
)

pytestmark = pytest.mark.tui


def make_report(*, failed: bool = False) -> DriverReport:
    report = DriverReport(scenario="smoke", size=(100, 30))
    report.steps.append(
        StepRecord(index=0, description="Send(text='hi')", status=STEP_PASSED, elapsed_ms=5, screen_text="hi")
    )
    if failed:
        report.steps.append(
            StepRecord(
                index=1,
                description="AssertText(expected='bye')",
                status=STEP_FAILED,
                elapsed_ms=1,
                screen_text="hi",
            )
        )
        report.failures.append("step 1: expected 'bye', actual 'hi'")
    report.screenshots.append("smoke/000-shot.svg")
    report.text_log = "== step 0 [passed]\nhi"
    return report


def test_passed_property() -> None:
    assert make_report().passed is True
    assert make_report(failed=True).passed is False


def test_report_to_dict_schema() -> None:
    payload = report_to_dict(make_report(failed=True))
    assert payload["scenario"] == "smoke"
    assert payload["size"] == {"cols": 100, "rows": 30}
    assert payload["passed"] is False
    steps = payload["steps"]
    assert isinstance(steps, list)
    assert steps[0]["index"] == 0
    assert steps[0]["status"] == STEP_PASSED
    assert "screen_text" in steps[0]
    json.dumps(payload)  # must be serializable


def test_write_json_creates_file(tmp_path) -> None:
    target = tmp_path / "nested" / "report.json"
    write_json(make_report(), target)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["passed"] is True
    assert loaded["scenario"] == "smoke"


def test_as_markdown_contains_everything_a_reader_needs() -> None:
    markdown = as_markdown(make_report(failed=True))
    assert "# driver report: smoke - FAILED" in markdown
    assert "terminal size: 100x30" in markdown
    assert "| 0 | Send(text='hi') | passed |" in markdown
    assert "step 1: expected 'bye', actual 'hi'" in markdown
    assert "smoke/000-shot.svg" in markdown
    assert "== step 0 [passed]" in markdown


def test_as_markdown_passed_verdict() -> None:
    assert "# driver report: smoke - PASSED" in as_markdown(make_report())
