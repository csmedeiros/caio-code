"""End-to-end driver runs: built-in scenarios, failures, artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from caio_code.infrastructure.observability.clocks import FixedClock
from caio_code.presentation.tui.driver.errors import DriverAssertionError
from caio_code.presentation.tui.driver.pilot_driver import TuiDriver
from caio_code.presentation.tui.driver.report import STEP_FAILED, STEP_PASSED
from caio_code.presentation.tui.driver.scenarios import SCENARIOS, build_scenario
from caio_code.presentation.tui.driver.steps import (
    AssertText,
    AssertWidget,
    Snapshot,
    Type,
    Wait,
)
from caio_code.presentation.tui.scripted import fixed_now

pytestmark = pytest.mark.tui

DRIVER_SIZE = (120, 32)


def make_driver(app_factory, reports_dir: Path, **kwargs) -> TuiDriver:
    return TuiDriver(
        app_factory,
        reports_dir=reports_dir,
        clock=FixedClock(fixed_now()),
        size=DRIVER_SIZE,
        **kwargs,
    )


class TestBuiltInScenarios:
    @pytest.mark.parametrize("name", sorted(SCENARIOS))
    async def test_scenario_passes_end_to_end(self, name: str, tmp_path: Path) -> None:
        app, steps = build_scenario(name)
        driver = make_driver(lambda: app, tmp_path)
        report = await driver.run_scenario(steps, name=name)
        assert report.passed, report.failures
        assert report.steps
        assert all(step.status == STEP_PASSED for step in report.steps)
        assert all(step.screen_text.strip() for step in report.steps)

    @pytest.mark.parametrize("name", sorted(SCENARIOS))
    async def test_scenario_writes_snapshot_pairs(self, name: str, tmp_path: Path) -> None:
        app, steps = build_scenario(name)
        driver = make_driver(lambda: app, tmp_path)
        report = await driver.run_scenario(steps, name=name)
        directory = tmp_path / name
        svgs = sorted(directory.glob("*.svg"))
        txts = sorted(directory.glob("*.txt"))
        assert svgs, f"{name} wrote no SVG"
        assert len(svgs) == len(txts)
        assert report.screenshots == [str(path) for path in svgs]
        assert svgs[0].read_text(encoding="utf-8").startswith("<svg")
        assert txts[0].read_text(encoding="utf-8").strip()


class TestFailures:
    async def test_failing_assert_raises_naming_the_step(self, tmp_path: Path) -> None:
        app, _ = build_scenario("smoke")
        driver = make_driver(lambda: app, tmp_path)
        steps = (Wait(1), AssertText("this is never on screen"))
        with pytest.raises(DriverAssertionError) as excinfo:
            await driver.run_scenario(steps, name="failing")
        error = excinfo.value
        assert error.step_index == 1
        assert "this is never on screen" in error.expected
        assert error.report is not None
        assert len(error.report.failures) == 1
        assert error.report.steps[1].status == STEP_FAILED

    async def test_continue_on_error_collects_without_raising(self, tmp_path: Path) -> None:
        app, _ = build_scenario("smoke")
        driver = make_driver(lambda: app, tmp_path, continue_on_error=True)
        steps = (AssertText("alpha"), AssertText("beta"), Snapshot("end"))
        report = await driver.run_scenario(steps, name="continuing")
        assert report.passed is False
        assert len(report.failures) == 2
        assert [step.status for step in report.steps] == [STEP_FAILED, STEP_FAILED, STEP_PASSED]
        assert (tmp_path / "continuing" / "002-end.svg").is_file()


class TestSteps:
    async def test_type_step_lands_in_the_composer(self, tmp_path: Path) -> None:
        app, _ = build_scenario("smoke")
        driver = make_driver(lambda: app, tmp_path)
        steps = (Type("hello there"), AssertText("hello there", within="#composer"))
        report = await driver.run_scenario(steps, name="typing")
        assert report.passed, report.failures

    async def test_assert_widget_negative(self, tmp_path: Path) -> None:
        app, _ = build_scenario("smoke")
        driver = make_driver(lambda: app, tmp_path)
        steps = (AssertWidget("#sidebar"), AssertWidget("#does-not-exist", exists=False))
        report = await driver.run_scenario(steps, name="widgets")
        assert report.passed, report.failures

    async def test_snapshot_file_naming(self, tmp_path: Path) -> None:
        app, _ = build_scenario("smoke")
        driver = make_driver(lambda: app, tmp_path)
        report = await driver.run_scenario((Snapshot("boot"),), name="naming")
        assert report.passed
        assert (tmp_path / "naming" / "000-boot.svg").is_file()
        assert (tmp_path / "naming" / "000-boot.txt").is_file()

    async def test_screen_text_matches_visible_render(self, tmp_path: Path) -> None:
        app, _ = build_scenario("smoke")
        driver = make_driver(lambda: app, tmp_path)
        report = await driver.run_scenario((Wait(1),), name="screen")
        assert "caio-code" in report.steps[0].screen_text
        assert not (tmp_path / "screen").exists()  # no snapshot was requested
