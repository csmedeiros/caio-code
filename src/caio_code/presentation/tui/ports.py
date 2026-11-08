"""The facade port the terminal interface depends on.

The app never talks to a model, a policy or a use case directly: it calls an
:class:`AgentFacade` and renders whatever arrives on the injected
:class:`~caio_code.domain.events.EventBus`. This module imports domain types
only, so the presentation layer stays decoupled from application and
infrastructure.

Event contract the app relies on (all from ``domain.events``):

``MessageAppended``
    Appends a bubble when ``message_id`` is new. When the ``message_id`` was
    already seen, the event is a *streaming delta*: the app replaces the text
    of that message in place. Facades stream by re-publishing the same
    ``message_id`` with growing ``preview`` text, then one final event.
``role='tool'``
    A ``MessageAppended`` with ``role='tool'`` whose ``message_id`` matches a
    pending ``ToolCallIssued.call_id`` carries the tool result preview.
``role='summary'``
    Rendered with the anchored-summary style (the compaction result).
``RunFinished.status``
    One of :data:`RUN_STATUS_COMPLETED`, :data:`RUN_STATUS_INTERRUPTED` or
    :data:`RUN_STATUS_ERROR`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from caio_code.domain.todo.items import TodoBoard
from caio_code.domain.usage.accounting import RunAccounting

DEFAULT_MODEL = "stub"
DEFAULT_POLICY = "none"

RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_INTERRUPTED = "interrupted"
RUN_STATUS_ERROR = "error"


@runtime_checkable
class AgentFacade(Protocol):
    """Everything the app is allowed to ask the agent for."""

    @property
    def run_id(self) -> str:
        """Identifier of the current (or most recent) run."""

    @property
    def board(self) -> TodoBoard:
        """Current todo board; the sidebar renders it on every update."""

    @property
    def accounting(self) -> RunAccounting:
        """Accumulated tokens, cache stats and cost of the current run."""

    @property
    def context(self) -> Mapping[str, Any]:
        """Record of the last context decision (``decision.as_record()``).

        Keys the inspector and the footer read: ``policy``, ``tokens_before``,
        ``tokens_after``, ``budget_tokens``, ``overflow_tokens``, ``kept`` and
        ``dropped``. Empty mapping when no decision happened yet.
        """

    async def send(self, text: str) -> None:
        """Start a turn with the given user text; publishes events on the bus."""

    async def interrupt(self) -> None:
        """Abort the running turn as soon as possible."""

    async def shutdown(self) -> None:
        """Release resources before the app exits."""
