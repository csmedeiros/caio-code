"""Headless driver: typed scenarios, Pilot execution, reports, CLI."""

from __future__ import annotations

from caio_code.presentation.tui.driver.errors import (
    DriverAssertionError,
    DriverError,
    ScenarioError,
    ScriptError,
    WidgetLookupError,
)
from caio_code.presentation.tui.driver.pilot_driver import AppFactory, TuiDriver
from caio_code.presentation.tui.driver.report import (
    DriverReport,
    StepRecord,
    as_markdown,
    report_to_dict,
    write_json,
)
from caio_code.presentation.tui.driver.scenarios import SCENARIOS, build_scenario
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
    parse_line,
    parse_script,
)

__all__ = [
    "SCENARIOS",
    "AppFactory",
    "AssertFooter",
    "AssertText",
    "AssertTodo",
    "AssertWidget",
    "DriverAssertionError",
    "DriverError",
    "DriverReport",
    "DriverStep",
    "Key",
    "Scenario",
    "ScenarioError",
    "ScriptError",
    "Send",
    "Snapshot",
    "StepRecord",
    "TuiDriver",
    "Type",
    "Wait",
    "WidgetLookupError",
    "as_markdown",
    "build_scenario",
    "parse_line",
    "parse_script",
    "report_to_dict",
    "write_json",
]
