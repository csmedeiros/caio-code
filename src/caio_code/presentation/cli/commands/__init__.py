"""CLI subcommands: one module per verb, each a plain ``int``-returning function."""

from __future__ import annotations

from caio_code.presentation.cli.commands.classify import classify_command
from caio_code.presentation.cli.commands.compact import compact_command
from caio_code.presentation.cli.commands.doctor import doctor_command
from caio_code.presentation.cli.commands.evaluate import evaluate_command
from caio_code.presentation.cli.commands.run import run_command
from caio_code.presentation.cli.commands.tui import tui_command

__all__ = [
    "classify_command",
    "compact_command",
    "doctor_command",
    "evaluate_command",
    "run_command",
    "tui_command",
]
