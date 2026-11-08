"""``caio-code tui``: launches the app with the scripted facade offline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from caio_code.presentation.cli.main import main

EXIT_OK = 0


@pytest.fixture
def captured_app(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch CaioCodeApp.run so no terminal is needed; capture the instance."""
    captured: dict[str, Any] = {}

    def fake_run(self: Any) -> None:
        captured["app"] = self

    monkeypatch.setattr("caio_code.presentation.tui.app.CaioCodeApp.run", fake_run)
    return captured


def test_tui_demo_launches_scripted_app(
    captured_app: dict[str, Any], workspace: Path
) -> None:
    code = main(["tui", "--demo", "--root", str(workspace)])
    assert code == EXIT_OK
    app = captured_app["app"]
    from caio_code.presentation.tui.scripted import ScriptedFacade

    assert isinstance(app._facade, ScriptedFacade)


def test_tui_stub_provider_defaults_to_scripted(
    captured_app: dict[str, Any], workspace: Path
) -> None:
    code = main(["tui", "--provider", "stub", "--root", str(workspace)])
    assert code == EXIT_OK
    from caio_code.presentation.tui.scripted import ScriptedFacade

    assert isinstance(captured_app["app"]._facade, ScriptedFacade)


def test_tui_real_facade_when_provider_is_live(
    captured_app: dict[str, Any],
    workspace: Path,
    fake_credentials: str,
) -> None:
    code = main(
        ["tui", "--provider", "openai_compatible", "--root", str(workspace)]
    )
    assert code == EXIT_OK
    from caio_code.application.agent.facade import AgentSessionFacade

    assert isinstance(captured_app["app"]._facade, AgentSessionFacade)
