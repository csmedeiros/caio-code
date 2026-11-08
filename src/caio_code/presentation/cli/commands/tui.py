"""``caio-code tui``: launch the Textual app with the real or scripted facade."""

from __future__ import annotations

from argparse import Namespace

from caio_code.domain.events import InMemoryEventBus
from caio_code.infrastructure.observability.clocks import (
    SequentialIdentifiers,
    SystemClock,
)
from caio_code.presentation.cli.composition import build_runner, load_cli_settings

EXIT_OK = 0


def tui_command(args: Namespace) -> int:
    # Lazy imports: only this command needs Textual and the TUI package.
    from caio_code.application.agent.facade import AgentSessionFacade
    from caio_code.presentation.tui.app import CaioCodeApp
    from caio_code.presentation.tui.scripted import ScriptedFacade, demo_script

    settings = load_cli_settings(args, with_root=True)
    bus = InMemoryEventBus()
    clock = SystemClock()
    identifiers = SequentialIdentifiers()

    scripted = bool(args.demo) or settings.provider.provider == "stub"
    if scripted:
        facade = ScriptedFacade(
            bus,
            clock,
            identifiers,
            script=demo_script(),
            model=settings.provider.model if settings.provider.provider != "stub" else "stub",
            policy=args.policy,
        )
    else:
        runner = build_runner(
            settings,
            policy_name=args.policy,
            bus=bus,
            clock=clock,
            identifiers=identifiers,
        )
        facade = AgentSessionFacade(runner)

    app = CaioCodeApp(facade, bus, config=settings.tui, clock=clock)
    app.run()
    return EXIT_OK


__all__ = ["tui_command"]
