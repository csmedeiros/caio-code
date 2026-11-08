"""Parser-level behaviour: unknown subcommands, help, exit codes."""

from __future__ import annotations

import pytest

from caio_code.presentation.cli.main import build_parser, main


def test_unknown_subcommand_exits_non_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["frobnicate"])
    assert excinfo.value.code != 0


def test_no_subcommand_exits_non_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


def test_parser_declares_every_subcommand() -> None:
    parser = build_parser()
    actions = {
        action.dest: action for action in parser._actions if action.dest == "command"
    }
    choices = set(actions["command"].choices)
    assert {"run", "tui", "compact", "evaluate", "doctor"} <= choices


def test_run_requires_task() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["run"])
    assert excinfo.value.code != 0


def test_console_script_entry_point_resolves() -> None:
    from caio_code.presentation.cli.main import main as entry

    assert callable(entry)
