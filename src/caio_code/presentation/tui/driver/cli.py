"""Command line entry point of the headless driver.

``python -m caio_code.presentation.tui.driver`` runs built-in scenarios or a
plain-text step script against the app, writes reports (JSON, Markdown, SVG,
txt) and exits non-zero when any assertion fails. This is how an AI agent
drives the TUI without a terminal: ``--stdin`` reads step lines until EOF.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from textual.app import App

from caio_code.domain.events import InMemoryEventBus
from caio_code.infrastructure.observability.clocks import (
    FixedClock,
    SequentialIdentifiers,
    SystemClock,
)
from caio_code.presentation.tui.app import CaioCodeApp
from caio_code.presentation.tui.driver.errors import DriverAssertionError, DriverError
from caio_code.presentation.tui.driver.pilot_driver import AppFactory, StepHook, TuiDriver
from caio_code.presentation.tui.driver.report import (
    REPORT_JSON_NAME,
    DriverReport,
    StepRecord,
    as_markdown,
    report_to_dict,
    write_json,
)
from caio_code.presentation.tui.driver.scenarios import (
    DEMO_MODEL,
    DEMO_POLICY,
    build_scenario,
    resolve_scenario_names,
)
from caio_code.presentation.tui.driver.steps import (
    ALL_SCENARIOS,
    DriverStep,
    Scenario,
    parse_script,
)
from caio_code.presentation.tui.scripted import ScriptedFacade, demo_script, fixed_now
from caio_code.presentation.tui.theme import DEFAULT_TERMINAL_SIZE

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
SIZE_SEPARATOR = "x"
SCRIPT_SCENARIO_NAME = "script"
DEFAULT_REPORTS_DIR = Path("/tmp/tui-reports")
STEP_LOG_FORMAT = "[{status}] {index:02d} {description}"


@dataclass(frozen=True, slots=True)
class DriverOptions:
    """Parsed command line; ``steps`` set means --script/--stdin mode."""

    scenarios: tuple[str, ...] = ()
    steps: tuple[DriverStep, ...] | None = None
    size: tuple[int, int] = DEFAULT_TERMINAL_SIZE
    reports_dir: Path = DEFAULT_REPORTS_DIR
    continue_on_error: bool = False
    json_out: Path | None = None
    markdown_out: Path | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m caio_code.presentation.tui.driver",
        description="Drive the caio-code TUI headlessly and write reports.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        metavar="NAME",
        help=f"built-in scenario to run (repeatable; '{ALL_SCENARIOS}' runs every one)",
    )
    parser.add_argument(
        "--script", type=Path, metavar="FILE", help="plain-text step file, one step per line"
    )
    parser.add_argument(
        "--stdin", action="store_true", help="read step lines from stdin until EOF"
    )
    parser.add_argument(
        "--size",
        default=f"{DEFAULT_TERMINAL_SIZE[0]}{SIZE_SEPARATOR}{DEFAULT_TERMINAL_SIZE[1]}",
        metavar="COLSxROWS",
        help="terminal size of the headless run",
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR, metavar="PATH",
        help="where snapshots and report.json files are written",
    )
    parser.add_argument(
        "--continue-on-error", action="store_true",
        help="keep running steps after a failed assertion",
    )
    parser.add_argument("--json", type=Path, default=None, metavar="OUT", dest="json_out")
    parser.add_argument("--markdown", type=Path, default=None, metavar="OUT", dest="markdown_out")
    return parser


def parse_size(raw: str) -> tuple[int, int]:
    """``COLSxROWS`` into a size tuple; anything else raises DriverError."""
    parts = raw.lower().split(SIZE_SEPARATOR)
    if len(parts) != 2:
        msg = f"--size must be COLSxROWS, got {raw!r}"
        raise DriverError(msg)
    try:
        cols, rows = int(parts[0]), int(parts[1])
    except ValueError as exc:
        msg = f"--size must be COLSxROWS integers, got {raw!r}"
        raise DriverError(msg) from exc
    minimum = 1
    if cols < minimum or rows < minimum:
        msg = f"--size dimensions must be positive, got {raw!r}"
        raise DriverError(msg)
    return cols, rows


def parse_options(argv: Sequence[str] | None) -> DriverOptions:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    steps: tuple[DriverStep, ...] | None = None
    if namespace.script is not None and namespace.stdin:
        parser.error("--script and --stdin are mutually exclusive")
    if namespace.script is not None:
        steps = tuple(parse_script(namespace.script.read_text(encoding="utf-8")))
    elif namespace.stdin:
        steps = tuple(parse_script(sys.stdin.read()))
    if not namespace.scenario and steps is None:
        parser.error("choose --scenario NAME (repeatable or 'all'), --script FILE or --stdin")
    return DriverOptions(
        scenarios=tuple(namespace.scenario),
        steps=steps,
        size=parse_size(namespace.size),
        reports_dir=namespace.reports_dir,
        continue_on_error=namespace.continue_on_error,
        json_out=namespace.json_out,
        markdown_out=namespace.markdown_out,
    )


def script_app_factory() -> App[object]:
    """App behind --script/--stdin: a ScriptedFacade replaying the demo turn."""
    bus = InMemoryEventBus()
    clock = FixedClock(fixed_now())
    facade = ScriptedFacade(
        bus,
        clock,
        SequentialIdentifiers(),
        script=demo_script(),
        model=DEMO_MODEL,
        policy=DEMO_POLICY,
    )
    return CaioCodeApp(facade, bus, clock=clock)


def _print_step(record: StepRecord) -> None:
    print(
        STEP_LOG_FORMAT.format(
            status=record.status, index=record.index, description=record.description
        )
    )


async def run_options(options: DriverOptions) -> int:
    """Run every requested scenario; return the process exit code."""
    targets: list[tuple[str, AppFactory, Scenario]] = []
    if options.steps is not None:
        targets.append((SCRIPT_SCENARIO_NAME, script_app_factory, options.steps))
    if options.scenarios:
        for name in resolve_scenario_names(options.scenarios):
            app, scenario = build_scenario(name)
            targets.append((name, lambda app=app: app, scenario))

    reports: list[DriverReport] = []
    exit_code = EXIT_OK
    printer: StepHook = _print_step
    for name, factory, scenario in targets:
        print(f"== scenario {name}")
        driver = TuiDriver(
            factory,
            reports_dir=options.reports_dir,
            clock=SystemClock(),
            size=options.size,
            continue_on_error=options.continue_on_error,
            on_step=printer,
        )
        try:
            report = await driver.run_scenario(scenario, name=name)
        except DriverAssertionError as assertion:
            report = assertion.report
            if report is None:
                raise
            exit_code = EXIT_FAILURE
        reports.append(report)
        scenario_dir = options.reports_dir / name
        write_json(report, scenario_dir / REPORT_JSON_NAME)
        verdict = "PASSED" if report.passed else "FAILED"
        print(f"== scenario {name}: {verdict} "
              f"({len(report.failures)} failed, report {scenario_dir / REPORT_JSON_NAME})")
        if not report.passed:
            for failure in report.failures:
                print(f"   - {failure}")
            exit_code = EXIT_FAILURE

    if options.json_out is not None:
        options.json_out.parent.mkdir(parents=True, exist_ok=True)
        payload = [report_to_dict(report) for report in reports]
        options.json_out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if options.markdown_out is not None:
        options.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        options.markdown_out.write_text(
            "\n\n".join(as_markdown(report) for report in reports) + "\n", encoding="utf-8"
        )
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    try:
        options = parse_options(argv)
    except DriverError as usage_error:
        print(f"error: {usage_error}", file=sys.stderr)
        return EXIT_USAGE
    try:
        return asyncio.run(run_options(options))
    except DriverError as driver_error:
        print(f"error: {driver_error}", file=sys.stderr)
        return EXIT_USAGE


__all__ = ["DriverOptions", "main", "parse_options", "parse_size", "run_options"]
