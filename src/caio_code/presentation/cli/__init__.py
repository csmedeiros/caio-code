"""Command-line interface.

The console-script entry point is ``caio_code.presentation.cli.main:main``.
``main`` is deliberately not re-exported here: a package attribute named
``main`` would shadow the :mod:`caio_code.presentation.cli.main` module.
"""

from __future__ import annotations

from caio_code.presentation.cli.main import build_parser

__all__ = ["build_parser"]
