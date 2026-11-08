"""Shared fixtures: offline facade, bus, fixed clock, app builder."""

from __future__ import annotations

import pytest

from caio_code.config import TuiConfig
from caio_code.domain.events import InMemoryEventBus
from caio_code.infrastructure.observability.clocks import FixedClock, SequentialIdentifiers
from caio_code.presentation.tui.app import CaioCodeApp
from caio_code.presentation.tui.scripted import Script, ScriptedFacade, fixed_now
from tests.presentation.tui.helpers import TuiRig


@pytest.fixture
def rig_factory():
    """Build a fresh rig per test; no state leaks between tests."""

    def build(script: Script = (), *, config: TuiConfig | None = None) -> TuiRig:
        bus = InMemoryEventBus()
        clock = FixedClock(fixed_now())
        identifiers = SequentialIdentifiers()
        facade = ScriptedFacade(bus, clock, identifiers, script=script)
        app = CaioCodeApp(facade, bus, config=config, clock=clock)
        return TuiRig(app=app, facade=facade, bus=bus, clock=clock, identifiers=identifiers)

    return build
