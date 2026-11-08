"""Integration tests of CaioCodeApp: boot, events to widgets, keybindings."""

from __future__ import annotations

import pytest
from textual.widgets import DataTable

from caio_code.config import TuiConfig
from caio_code.domain.events import RunFinished
from caio_code.domain.usage.accounting import TokenUsage
from caio_code.presentation.tui.app import ContextInspectorScreen
from caio_code.presentation.tui.driver.text import screen_text
from caio_code.presentation.tui.ports import RUN_STATUS_INTERRUPTED
from caio_code.presentation.tui.scripted import (
    AssistantStep,
    AwaitInterruptStep,
    ContextStep,
    FinishStep,
    GuardrailStep,
    TodoStep,
    ToolStep,
    UsageStep,
)
from caio_code.presentation.tui.widgets.composer import Composer
from caio_code.presentation.tui.widgets.message_list import MessageList
from caio_code.presentation.tui.widgets.todo_sidebar import TodoSidebar
from caio_code.presentation.tui.widgets.usage_footer import (
    OVER_BUDGET_LABEL,
    STATUS_INTERRUPTED,
    UsageFooter,
)
from tests.presentation.tui.helpers import SETTLE_SECONDS, TEST_SIZE, send_and_settle

pytestmark = pytest.mark.tui


class TestBoot:
    async def test_boots_with_sidebar_footer_and_focused_composer(self, rig_factory) -> None:
        rig = rig_factory()
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            assert rig.app.query_one("#sidebar", TodoSidebar).display is True
            footer = rig.app.query_one("#usage-footer", UsageFooter)
            assert "idle" in footer.text
            assert rig.app.focused is rig.app.query_one("#composer", Composer)

    async def test_sidebar_width_comes_from_config(self, rig_factory) -> None:
        width = 40
        rig = rig_factory(config=TuiConfig(sidebar_width=width))
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            assert rig.app.query_one("#sidebar").size.width == width


class TestConversation:
    async def test_send_appends_user_and_assistant_bubbles(self, rig_factory) -> None:
        rig = rig_factory((AssistantStep("Hi there, how can I help?", deltas=3), FinishStep()))
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "hello")
            transcript = rig.app.query_one("#transcript", MessageList)
            bubbles = [entry for entry in transcript.entries if hasattr(entry, "role")]
            assert [bubble.role for bubble in bubbles] == ["user", "assistant"]
            assert bubbles[0].text == "hello"
            assert bubbles[1].text == "Hi there, how can I help?"
            assert "Hi there" in screen_text(rig.app)

    async def test_streaming_deltas_update_one_bubble_in_place(self, rig_factory) -> None:
        rig = rig_factory((AssistantStep("abcdefgh", deltas=4), FinishStep()))
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "go")
            transcript = rig.app.query_one("#transcript", MessageList)
            assistants = [
                entry
                for entry in transcript.entries
                if hasattr(entry, "role") and entry.role == "assistant"
            ]
            assert len(assistants) == 1
            assert assistants[0].text == "abcdefgh"

    async def test_stream_deltas_disabled_keeps_first_delta(self, rig_factory) -> None:
        rig = rig_factory(
            (AssistantStep("abcdefgh", deltas=4), FinishStep()),
            config=TuiConfig(stream_deltas=False),
        )
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "go")
            transcript = rig.app.query_one("#transcript", MessageList)
            assistants = [
                entry
                for entry in transcript.entries
                if hasattr(entry, "role") and entry.role == "assistant"
            ]
            assert len(assistants) == 1
            assert assistants[0].text == "ab"

    async def test_tool_call_renders_panel_with_result_and_status(self, rig_factory) -> None:
        rig = rig_factory(
            (
                ToolStep(
                    tool="read_file",
                    arguments='{"path": "src/main.py"}',
                    result="print('hi')",
                    truncated=True,
                ),
                FinishStep(),
            )
        )
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "read it")
            panels = rig.app.query(".tool-panel")
            assert len(panels) == 1
            panel_text = rig.app.query_one("#transcript", MessageList).full_text()
            assert "tool read_file" in panel_text
            assert "print('hi')" in panel_text
            assert "done" in panel_text
            assert "[truncated]" in panel_text
            assert "ms" in panel_text

    async def test_guardrail_fires_system_bubble(self, rig_factory) -> None:
        rig = rig_factory(
            (GuardrailStep(guardrail="repeat", detail="same call x3"), FinishStep())
        )
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "loop")
            full = rig.app.query_one("#transcript", MessageList).full_text()
            assert "guardrail repeat: same call x3" in full

    async def test_usage_event_updates_footer_tokens_and_cost(self, rig_factory) -> None:
        rig = rig_factory(
            (
                UsageStep(
                    usage=TokenUsage(input_tokens=1_000, output_tokens=100, cached_input_tokens=500)
                ),
                FinishStep(),
            )
        )
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "go")
            footer = rig.app.query_one("#usage-footer", UsageFooter).text
            assert "in 1.0k" in footer
            assert "out 100" in footer
            assert "cache 50%" in footer
            assert "$" in footer


class TestTodoSidebar:
    async def test_board_event_updates_counts_and_header(self, rig_factory) -> None:
        rig = rig_factory(
            (
                TodoStep(
                    (
                        ("first task", "completed"),
                        ("second task", "in_progress"),
                        ("third task", "pending"),
                        ("dropped task", "cancelled"),
                    )
                ),
                FinishStep(),
            )
        )
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "plan")
            sidebar = rig.app.query_one("#sidebar", TodoSidebar)
            assert sidebar.header_text == "1/3 · 33%"
            assert len(sidebar.query(".todo-item")) == 4
            assert len(sidebar.query(".todo-in_progress")) == 1
            assert len(sidebar.query(".todo-cancelled")) == 1


class TestContextFooter:
    async def test_overflow_decision_marks_footer_over_budget(self, rig_factory) -> None:
        rig = rig_factory(
            (
                ContextStep(
                    policy="baseline",
                    tokens_before=12_400,
                    tokens_after=12_400,
                    budget_tokens=8_000,
                    kept=20,
                ),
                FinishStep(),
            )
        )
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "go")
            footer = rig.app.query_one("#usage-footer", UsageFooter)
            assert "12.4k / 8.0k (155%)" in footer.text
            assert OVER_BUDGET_LABEL in footer.text
            assert footer.has_class("over-budget")

    async def test_ctrl_u_opens_and_escape_closes_inspector(self, rig_factory) -> None:
        rig = rig_factory(
            (
                ContextStep(
                    policy="sliding_window",
                    tokens_before=9_000,
                    tokens_after=7_000,
                    budget_tokens=8_000,
                    kept=9,
                    dropped=4,
                ),
                FinishStep(),
            )
        )
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await send_and_settle(pilot, rig.app, "go")
            await pilot.press("ctrl+u")
            await pilot.pause()
            assert isinstance(rig.app.screen, ContextInspectorScreen)
            table = rig.app.screen.query_one("#context-inspector", DataTable)
            assert table.row_count > 0
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(rig.app.screen, ContextInspectorScreen)


class TestInterruptAndQuit:
    async def test_escape_interrupts_running_turn(self, rig_factory) -> None:
        rig = rig_factory(
            (
                AssistantStep("thinking hard", deltas=2),
                AwaitInterruptStep(),
                FinishStep(),
            )
        )
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            composer = rig.app.query_one("#composer", Composer)
            composer.focus()
            composer.insert("start the long run")
            await pilot.press("enter")
            await pilot.pause(SETTLE_SECONDS)
            await pilot.press("escape")
            await pilot.pause(SETTLE_SECONDS)
            footer = rig.app.query_one("#usage-footer", UsageFooter)
            assert STATUS_INTERRUPTED in footer.text
            finished = [event for event in rig.facade.events if isinstance(event, RunFinished)]
            assert finished[-1].status == RUN_STATUS_INTERRUPTED

    async def test_ctrl_q_shuts_facade_down_and_quits(self, rig_factory) -> None:
        rig = rig_factory()
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+q")
        assert rig.facade.shutdown_calls == 1

    async def test_ctrl_t_hides_and_shows_sidebar(self, rig_factory) -> None:
        rig = rig_factory()
        async with rig.app.run_test(headless=True, size=TEST_SIZE) as pilot:
            await pilot.pause()
            sidebar = rig.app.query_one("#sidebar", TodoSidebar)
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert sidebar.display is False
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert sidebar.display is True
