"""The headless driver: runs typed scenarios through Textual's Pilot.

``TuiDriver`` boots the app with ``App.run_test(headless=True)``, executes one
step at a time, and records after every step: index, description, pass/fail,
elapsed milliseconds (from the injected clock) and the screen text. Snapshots
write an SVG plus a txt dump into ``reports_dir/<scenario>/``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from textual.app import App
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import TextArea

from caio_code.domain.ports.time import Clock
from caio_code.infrastructure.observability.clocks import SystemClock
from caio_code.presentation.tui.driver.errors import (
    DriverAssertionError,
    DriverError,
    WidgetLookupError,
)
from caio_code.presentation.tui.driver.report import (
    STEP_ERROR,
    STEP_FAILED,
    STEP_PASSED,
    DriverReport,
    StepRecord,
)
from caio_code.presentation.tui.driver.steps import (
    AssertFooter,
    AssertText,
    AssertTodo,
    AssertWidget,
    DriverStep,
    Key,
    Scenario,
    Send,
    Snapshot,
    Type,
    Wait,
)
from caio_code.presentation.tui.driver.text import screen_text, widget_text
from caio_code.presentation.tui.theme import (
    COMPOSER_ID,
    DEFAULT_TERMINAL_SIZE,
    SIDEBAR_ID,
    USAGE_FOOTER_ID,
)

AppFactory = Callable[[], App[object]]
StepHook = Callable[[StepRecord], None]

DEFAULT_SCENARIO_NAME = "scenario"
SNAPSHOT_SVG_SUFFIX = ".svg"
SNAPSHOT_TXT_SUFFIX = ".txt"
SNAPSHOT_INDEX_PAD = 3
MS_PER_SECOND = 1_000
ENTER_KEY = "enter"
TODO_ITEM_SELECTOR = ".todo-item"
TODO_IN_PROGRESS_SELECTOR = ".todo-in_progress"
TODO_COMPLETED_SELECTOR = ".todo-completed"


class TuiDriver:
    """Executes scenarios against an app instance built by ``app_factory``."""

    def __init__(
        self,
        app_factory: AppFactory,
        *,
        reports_dir: Path,
        clock: Clock | None = None,
        size: tuple[int, int] = DEFAULT_TERMINAL_SIZE,
        continue_on_error: bool = False,
        on_step: StepHook | None = None,
    ) -> None:
        self._app_factory = app_factory
        self._reports_dir = Path(reports_dir)
        self._clock = clock or SystemClock()
        self._size = size
        self._continue_on_error = continue_on_error
        self._on_step = on_step

    async def run_scenario(
        self, scenario: Scenario, *, name: str = DEFAULT_SCENARIO_NAME
    ) -> DriverReport:
        """Run every step inside one ``App.run_test`` session."""
        report = DriverReport(scenario=name, size=self._size)
        log_lines: list[str] = []
        failure: DriverAssertionError | None = None
        app = self._app_factory()
        async with app.run_test(headless=True, size=self._size) as pilot:
            await pilot.pause()
            for index, step in enumerate(scenario):
                record, error = await self._run_step(app, pilot, step, index, name, report)
                report.steps.append(record)
                log_lines.append(f"== step {index}: {step.describe()} [{record.status}]")
                log_lines.append(record.screen_text)
                if self._on_step is not None:
                    self._on_step(record)
                if error is not None:
                    report.failures.append(str(error))
                    failure = error
                    if not self._continue_on_error:
                        break
        report.text_log = "\n".join(log_lines)
        if failure is not None and not self._continue_on_error:
            failure.report = report
            raise failure
        return report

    async def _run_step(
        self,
        app: App[object],
        pilot: Pilot,
        step: DriverStep,
        index: int,
        scenario: str,
        report: DriverReport,
    ) -> tuple[StepRecord, DriverAssertionError | None]:
        started = self._clock.monotonic_ms()
        error: DriverAssertionError | None = None
        status = STEP_PASSED
        try:
            await self._execute(app, pilot, step, index, scenario, report)
        except DriverAssertionError as assertion:
            status = STEP_FAILED
            error = assertion
        except DriverError as driver_error:
            status = STEP_ERROR
            error = DriverAssertionError(index, "step to run", f"error: {driver_error}")
        except Exception as exc:
            status = STEP_ERROR
            error = DriverAssertionError(index, "step to run", f"error: {exc!r}")
        await pilot.pause()
        elapsed_ms = self._clock.monotonic_ms() - started
        record = StepRecord(
            index=index,
            description=step.describe(),
            status=status,
            elapsed_ms=elapsed_ms,
            screen_text=screen_text(app),
        )
        return record, error

    async def _execute(
        self,
        app: App[object],
        pilot: Pilot,
        step: DriverStep,
        index: int,
        scenario: str,
        report: DriverReport,
    ) -> None:
        match step:
            case Type():
                await self._type(app, pilot, step.text)
            case Send():
                await self._type(app, pilot, step.text)
                await pilot.press(ENTER_KEY)
            case Key():
                await pilot.press(step.name)
            case Wait():
                await pilot.pause(step.ms / MS_PER_SECOND)
            case AssertText():
                self._assert_text(app, step, index)
            case AssertTodo():
                self._assert_todo(app, step, index)
            case AssertFooter():
                self._assert_footer(app, step, index)
            case AssertWidget():
                self._assert_widget(app, step, index)
            case Snapshot():
                await self._snapshot(app, pilot, step.name, index, scenario, report)
            case _:
                msg = f"unknown step type {type(step).__name__!r}"
                raise DriverError(msg)

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    async def _type(self, app: App[object], pilot: Pilot, text: str) -> None:
        composer = self._query_one(app, f"#{COMPOSER_ID}", TextArea)
        composer.focus()
        await pilot.pause()
        composer.insert(text)
        await pilot.pause()

    def _assert_text(self, app: App[object], step: AssertText, index: int) -> None:
        if step.within is None:
            actual = screen_text(app)
        else:
            actual = widget_text(self._query_one(app, step.within))
        if step.expected not in actual:
            raise DriverAssertionError(index, step.expected, actual)

    def _assert_todo(self, app: App[object], step: AssertTodo, index: int) -> None:
        try:
            sidebar = app.screen.query_one(f"#{SIDEBAR_ID}")
        except Exception as exc:  # textual NoMatches/DuplicateWidget
            msg = f"sidebar #{SIDEBAR_ID} not found: {exc}"
            raise WidgetLookupError(msg) from exc
        counts = {
            "count": len(sidebar.query(TODO_ITEM_SELECTOR)),
            "in_progress": len(sidebar.query(TODO_IN_PROGRESS_SELECTOR)),
            "completed": len(sidebar.query(TODO_COMPLETED_SELECTOR)),
        }
        for field_name, expected in (
            ("count", step.count),
            ("in_progress", step.in_progress),
            ("completed", step.completed),
        ):
            if expected is not None and counts[field_name] != expected:
                raise DriverAssertionError(
                    index,
                    f"{field_name}={expected}",
                    f"{field_name}={counts[field_name]}",
                )

    def _assert_footer(self, app: App[object], step: AssertFooter, index: int) -> None:
        footer = self._query_one(app, f"#{USAGE_FOOTER_ID}")
        actual = widget_text(footer)
        for expected in step.contains:
            if expected not in actual:
                raise DriverAssertionError(index, expected, actual)

    def _assert_widget(self, app: App[object], step: AssertWidget, index: int) -> None:
        matches = app.screen.query(step.query)
        exists = len(matches) > 0
        if exists != step.exists:
            expected = f"widget {step.query!r} exists={step.exists}"
            raise DriverAssertionError(index, expected, f"exists={exists}")

    async def _snapshot(
        self,
        app: App[object],
        pilot: Pilot,
        name: str,
        index: int,
        scenario: str,
        report: DriverReport,
    ) -> None:
        await pilot.pause()
        directory = self._reports_dir / scenario
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{index:0{SNAPSHOT_INDEX_PAD}d}-{name}"
        svg_path = directory / f"{stem}{SNAPSHOT_SVG_SUFFIX}"
        txt_path = directory / f"{stem}{SNAPSHOT_TXT_SUFFIX}"
        svg_path.write_text(app.export_screenshot(), encoding="utf-8")
        txt_path.write_text(screen_text(app) + "\n", encoding="utf-8")
        report.screenshots.append(str(svg_path))

    def _query_one(
        self, app: App[object], selector: str, expected_type: type[Widget] | None = None
    ) -> Widget:
        try:
            if expected_type is None:
                return app.screen.query_one(selector)
            return app.screen.query_one(selector, expected_type)
        except Exception as exc:  # textual NoMatches/DuplicateWidget/WrongType
            msg = f"selector {selector!r} did not resolve to one widget: {exc}"
            raise WidgetLookupError(msg) from exc
