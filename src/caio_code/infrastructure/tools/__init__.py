"""Tool adapters: sandboxed SWE tools and the deepagents backend selection."""

from __future__ import annotations

from caio_code.infrastructure.tools.deepagents_backend import build_backend
from caio_code.infrastructure.tools.filesystem import FilesystemToolset
from caio_code.infrastructure.tools.sandbox import Sandbox
from caio_code.infrastructure.tools.search import SearchToolset
from caio_code.infrastructure.tools.shell import ShellToolset, shell_backend

__all__ = [
    "FilesystemToolset",
    "Sandbox",
    "SearchToolset",
    "ShellToolset",
    "build_backend",
    "shell_backend",
]
