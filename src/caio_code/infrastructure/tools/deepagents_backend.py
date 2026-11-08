"""Backend selection for the deepagents runtime.

``build_backend`` picks the backend from the sandbox configuration: a real
directory on disk gets :class:`~deepagents.backends.FilesystemBackend` rooted
there (the TUI runs against the user's repository); anything else falls back to
the ephemeral :class:`~deepagents.backends.StateBackend` (the eval harness runs
on a temporary, sometimes virtual, workspace and must not touch the host). The
rationale is documented in this directory's ``AGENTS.md``.
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import BackendProtocol, FilesystemBackend, StateBackend

from caio_code.config import Settings


def build_backend(settings: Settings) -> BackendProtocol:
    """Filesystem backend when the sandbox root exists, state backend otherwise."""
    root = Path(settings.sandbox.root).expanduser()
    if root.is_dir():
        # virtual_mode=True: caminhos são virtuais sob root_dir e traversal é
        # erro no próprio backend — mesma filosofia da nossa Sandbox.
        return FilesystemBackend(root_dir=root, virtual_mode=True)
    return StateBackend()


__all__ = ["build_backend"]
