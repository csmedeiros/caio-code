"""The AgentFacade contract and theme constants (pure units, no terminal)."""

from __future__ import annotations

import re

import pytest

from caio_code.domain.events import InMemoryEventBus
from caio_code.infrastructure.observability.clocks import FixedClock, SequentialIdentifiers
from caio_code.presentation.tui import ports, theme
from caio_code.presentation.tui.ports import AgentFacade
from caio_code.presentation.tui.scripted import ScriptedFacade, fixed_now

pytestmark = pytest.mark.tui

HEX_COLOR = re.compile(r"^#[0-9a-f]{6}$")


def make_facade() -> ScriptedFacade:
    return ScriptedFacade(
        InMemoryEventBus(), FixedClock(fixed_now()), SequentialIdentifiers(), script=()
    )


class TestFacadeProtocol:
    def test_scripted_facade_satisfies_protocol(self) -> None:
        assert isinstance(make_facade(), AgentFacade)

    def test_initial_state(self) -> None:
        facade = make_facade()
        assert facade.run_id == ""
        assert len(facade.board) == 0
        assert facade.context == {}
        assert facade.accounting.usage.total_tokens == 0

    async def test_interrupt_when_idle_is_a_noop(self) -> None:
        facade = make_facade()
        await facade.interrupt()
        await facade.send("hello")
        assert facade.events[-1].__class__.__name__ == "RunFinished"

    def test_run_status_constants_are_distinct(self) -> None:
        statuses = {
            ports.RUN_STATUS_COMPLETED,
            ports.RUN_STATUS_INTERRUPTED,
            ports.RUN_STATUS_ERROR,
        }
        assert len(statuses) == 3


class TestTheme:
    def test_every_role_has_a_color_and_a_label(self) -> None:
        assert set(theme.ROLE_COLORS) == set(theme.ROLE_LABELS)
        assert {"user", "assistant", "tool", "system", "summary"} <= set(theme.ROLE_COLORS)

    def test_colors_are_hex_light_on_dark(self) -> None:
        palette = [
            value
            for name, value in vars(theme).items()
            if name.startswith("COLOR_") and isinstance(value, str)
        ]
        assert palette
        for color in palette:
            assert HEX_COLOR.match(color), color

    def test_default_terminal_size_is_usable(self) -> None:
        cols, rows = theme.DEFAULT_TERMINAL_SIZE
        assert cols >= 80
        assert rows >= 24

    def test_app_css_references_the_widget_ids(self) -> None:
        for widget_id in (
            theme.MESSAGE_LIST_ID,
            theme.SIDEBAR_ID,
            theme.COMPOSER_ID,
            theme.USAGE_FOOTER_ID,
        ):
            assert f"#{widget_id}" in theme.APP_CSS
