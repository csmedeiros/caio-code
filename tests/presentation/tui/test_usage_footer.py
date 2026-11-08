"""UsageFooter formatting and state transitions."""

from __future__ import annotations

from decimal import Decimal

import pytest
from textual.app import App, ComposeResult

from caio_code.presentation.tui.widgets.usage_footer import (
    OVER_BUDGET_LABEL,
    STATUS_RUNNING,
    FooterState,
    UsageFooter,
    format_cost,
    format_percent,
    format_token_count,
)
from tests.presentation.tui.helpers import TEST_SIZE

pytestmark = pytest.mark.tui


class TestFormatters:
    def test_token_counts(self) -> None:
        assert format_token_count(850) == "850"
        assert format_token_count(12_400) == "12.4k"
        assert format_token_count(8_000) == "8.0k"

    def test_percent(self) -> None:
        assert format_percent(1.55) == "155%"
        assert format_percent(0.428) == "43%"

    def test_cost_has_four_decimals(self) -> None:
        assert format_cost(Decimal("0.0123456")) == "$0.0123"
        assert format_cost(Decimal("0")) == "$0.0000"


class TestFooterState:
    def test_over_budget_render(self) -> None:
        state = FooterState(
            model="qwen3.8-max",
            policy="baseline",
            used_tokens=12_400,
            budget_tokens=8_000,
            input_tokens=12_400,
            output_tokens=300,
            cache_hit_ratio=0.42,
            cost_usd=Decimal("0.0310"),
            status=STATUS_RUNNING,
        )
        rendered = state.render()
        assert "12.4k / 8.0k (155%)" in rendered
        assert OVER_BUDGET_LABEL in rendered
        assert "cache 42%" in rendered
        assert "$0.0310" in rendered
        assert state.over_budget is True

    def test_within_budget_has_no_marker(self) -> None:
        state = FooterState(used_tokens=4_100, budget_tokens=8_000)
        assert OVER_BUDGET_LABEL not in state.render()
        assert state.over_budget is False

    def test_unknown_context(self) -> None:
        assert "ctx -" in FooterState().render()


class FooterHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield UsageFooter()


async def test_footer_widget_reacts_to_state_updates() -> None:
    app = FooterHarness()
    async with app.run_test(headless=True, size=TEST_SIZE) as pilot:
        footer = app.query_one("#usage-footer", UsageFooter)
        assert footer.text.endswith("idle")
        footer.update_state(status=STATUS_RUNNING, used_tokens=9_000, budget_tokens=8_000)
        await pilot.pause()
        assert OVER_BUDGET_LABEL in footer.text
        assert footer.has_class("over-budget")
        footer.update_state(used_tokens=1_000)
        await pilot.pause()
        assert OVER_BUDGET_LABEL not in footer.text
        assert not footer.has_class("over-budget")
