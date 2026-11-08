"""Shared fixtures: offline settings, bus+recorder, fixed clock, runner builder."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from caio_code.application.agent.runner import AgentRunner
from caio_code.application.agent.stub_model import StubChatModel, StubTurn
from caio_code.config import (
    ProviderConfig,
    SandboxConfig,
    Settings,
    WindowConfig,
)
from caio_code.domain.events import DomainEvent, InMemoryEventBus
from caio_code.infrastructure.observability.bus import EventRecorder
from caio_code.infrastructure.observability.clocks import FixedClock, SequentialIdentifiers

FIXED_START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_TOKENS = 8_000


def make_settings(root: Path, *, window_tokens: int = WINDOW_TOKENS) -> Settings:
    return Settings(
        window=WindowConfig(tokens=window_tokens),
        provider=ProviderConfig(provider="stub", model="stub", aux_provider="stub", aux_model="stub"),
        sandbox=SandboxConfig(root=root),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "a.txt").write_text("alpha\n", encoding="utf-8")
    (root / "b.py").write_text("print('beta')\n", encoding="utf-8")
    return root


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def recorder(bus: InMemoryEventBus) -> EventRecorder:
    recorder = EventRecorder()
    bus.subscribe(recorder)
    return recorder


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(FIXED_START)


@pytest.fixture
def identifiers() -> SequentialIdentifiers:
    return SequentialIdentifiers()


@pytest.fixture
def settings(workspace: Path) -> Settings:
    return make_settings(workspace)


def event_names(events: list[DomainEvent]) -> list[str]:
    return [type(event).__name__ for event in events]


def runner_factory(
    settings: Settings,
    bus: InMemoryEventBus,
    clock: FixedClock,
    identifiers: SequentialIdentifiers,
) -> Callable[..., AgentRunner]:
    """Build a runner whose stub chat model replays ``turns``."""

    def build(
        turns: tuple[StubTurn, ...] = (),
        *,
        policy: str = "sliding_window",
        chat_model: Any | None = None,
        toolsets: Any | None = None,
    ) -> AgentRunner:
        from caio_code.application.agent.runner import AgentRunner as Runner
        from caio_code.domain.conversation.budget import TokenBudget
        from caio_code.presentation.cli.composition import (
            build_dependencies,
            build_policy_pipeline,
            resolve_system_prompt,
        )

        model = chat_model or StubChatModel(clock=clock, turns=tuple(turns))
        deps = build_dependencies(
            settings,
            bus=bus,
            clock=clock,
            identifiers=identifiers,
            chat_model=model,
        )
        if toolsets is not None:
            deps = dataclasses.replace(deps, toolsets=toolsets)
        runner = Runner(deps)
        pipeline = build_policy_pipeline(settings, policy)
        runner.build_agent(
            policy=pipeline,
            budget=TokenBudget(settings.window.tokens),
            system_prompt=resolve_system_prompt(settings, policy_name=pipeline.name),
        )
        return runner

    return build


@pytest.fixture
def make_runner(
    settings: Settings,
    bus: InMemoryEventBus,
    clock: FixedClock,
    identifiers: SequentialIdentifiers,
) -> Iterator[Callable[..., AgentRunner]]:
    yield runner_factory(settings, bus, clock, identifiers)


@pytest.fixture
def replace_deps() -> Callable[..., Any]:
    def replace(deps: Any, **changes: Any) -> Any:
        return dataclasses.replace(deps, **changes)

    return replace
