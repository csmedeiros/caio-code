"""Scenario registry: names, expansion, typed errors."""

from __future__ import annotations

import pytest

from caio_code.presentation.tui.app import CaioCodeApp
from caio_code.presentation.tui.driver.errors import ScenarioError
from caio_code.presentation.tui.driver.scenarios import (
    SCENARIOS,
    build_scenario,
    resolve_scenario_names,
)

pytestmark = pytest.mark.tui

REQUIRED_BUILTINS = ("smoke", "todo_sidebar", "compaction", "interrupt")


def test_required_builtins_are_registered() -> None:
    for name in REQUIRED_BUILTINS:
        assert name in SCENARIOS


def test_resolve_all_expands_registry_in_order() -> None:
    assert resolve_scenario_names(["all"]) == list(SCENARIOS)


def test_resolve_deduplicates_keeping_order() -> None:
    assert resolve_scenario_names(["smoke", "interrupt", "smoke"]) == ["smoke", "interrupt"]


def test_resolve_unknown_name_raises() -> None:
    with pytest.raises(ScenarioError, match="unknown scenario 'nope'"):
        resolve_scenario_names(["nope"])


def test_resolve_empty_request_raises() -> None:
    with pytest.raises(ScenarioError, match="no scenario"):
        resolve_scenario_names([])


def test_build_scenario_returns_fresh_app_and_steps() -> None:
    for name in REQUIRED_BUILTINS:
        app, steps = build_scenario(name)
        assert isinstance(app, CaioCodeApp)
        assert steps
        other_app, _ = build_scenario(name)
        assert other_app is not app


def test_build_unknown_scenario_raises() -> None:
    with pytest.raises(ScenarioError):
        build_scenario("missing")
