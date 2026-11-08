"""Facade adapting :class:`AgentRunner` to the TUI's ``AgentFacade`` protocol.

The app calls ``send``/``interrupt``/``shutdown`` and reads
``run_id``/``board``/``accounting``/``context``; everything else arrives as
domain events on the bus, which the runner already publishes -- the facade
republishes nothing and holds no state of its own beyond the last result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from caio_code.application.agent.runner import AgentRunner
from caio_code.application.agent.session import AgentRunResult
from caio_code.domain.todo.items import TodoBoard
from caio_code.domain.usage.accounting import RunAccounting


class AgentSessionFacade:
    """Implements ``presentation.tui.ports.AgentFacade`` over the runner."""

    def __init__(self, runner: AgentRunner) -> None:
        self._runner = runner
        self._last_result: AgentRunResult | None = None

    @property
    def run_id(self) -> str:
        return self._runner.run_id

    @property
    def board(self) -> TodoBoard:
        return self._runner.board

    @property
    def accounting(self) -> RunAccounting:
        return self._runner.accounting

    @property
    def context(self) -> Mapping[str, Any]:
        snapshot = self._runner.context
        return snapshot.as_record() if snapshot is not None else {}

    @property
    def last_result(self) -> AgentRunResult | None:
        return self._last_result

    async def send(self, text: str) -> None:
        """Run one turn; events reach the app through the bus."""
        self._last_result = await self._runner.run(text)

    async def interrupt(self) -> None:
        self._runner.interrupt()

    async def shutdown(self) -> None:
        self._runner.interrupt()


__all__ = ["AgentSessionFacade"]
