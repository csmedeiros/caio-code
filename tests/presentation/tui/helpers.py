"""Shared test helpers for the TUI suite (importable as ``helpers``)."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import App
from textual.pilot import Pilot

from caio_code.domain.events import InMemoryEventBus
from caio_code.infrastructure.observability.clocks import FixedClock, SequentialIdentifiers
from caio_code.presentation.tui.app import CaioCodeApp
from caio_code.presentation.tui.scripted import ScriptedFacade
from caio_code.presentation.tui.theme import COMPOSER_ID, DEFAULT_TERMINAL_SIZE
from caio_code.presentation.tui.widgets.composer import Composer

TEST_SIZE = DEFAULT_TERMINAL_SIZE
SETTLE_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class TuiRig:
    """One wired app: facade, bus and clock shared by a test."""

    app: CaioCodeApp
    facade: ScriptedFacade
    bus: InMemoryEventBus
    clock: FixedClock
    identifiers: SequentialIdentifiers


async def send_and_settle(pilot: Pilot, app: App[object], text: str) -> None:
    """Type ``text`` into the composer and press enter, then let the loop run."""
    composer = app.query_one(f"#{COMPOSER_ID}", Composer)
    composer.focus()
    composer.insert(text)
    await pilot.press("enter")
    await pilot.pause(SETTLE_SECONDS)
