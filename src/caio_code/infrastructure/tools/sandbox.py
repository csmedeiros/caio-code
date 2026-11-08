"""Path confinement: every tool resolves its paths through :class:`Sandbox`.

A path that leaves the root — via ``..``, an absolute path outside the root, or
a symlink pointing out — is an error (``SandboxEscapeError``), never a warning.
The check resolves the full path *and* each existing parent, so a symlinked
directory inside the root cannot be used as a tunnel.
"""

from __future__ import annotations

from pathlib import Path

from caio_code.config import SandboxConfig
from caio_code.domain.errors import SandboxEscapeError


class Sandbox:
    """Resolves and validates paths against a fixed root."""

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        self._root = config.root.expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def config(self) -> SandboxConfig:
        return self._config

    def resolve(self, path: str | Path) -> Path:
        """Absolute, fully resolved path inside the root.

        Raises ``SandboxEscapeError`` naming the offending value when the path
        escapes the root textually, through a symlink, or through any of its
        existing parents.
        """
        candidate = self._root / Path(path)
        for parent in (candidate, *candidate.parents):
            if parent == self._root:
                break
            if not parent.exists():
                continue
            resolved_parent = parent.resolve()
            if not resolved_parent.is_relative_to(self._root):
                msg = (
                    f"path {str(path)!r} escapes sandbox root {str(self._root)!r}: "
                    f"component {str(parent)!r} resolves to {str(resolved_parent)!r}"
                )
                raise SandboxEscapeError(msg)
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._root):
            msg = (
                f"path {str(path)!r} escapes sandbox root {str(self._root)!r}: "
                f"resolves to {str(resolved)!r}"
            )
            raise SandboxEscapeError(msg)
        return resolved

    def is_within(self, path: str | Path) -> bool:
        """``True`` when the path resolves inside the root; never raises."""
        try:
            resolved = (self._root / Path(path)).resolve()
        except OSError:
            return False
        return resolved.is_relative_to(self._root)

    def relative(self, path: str | Path) -> str:
        """Path relative to the root, in POSIX form (the root itself is ``.``)."""
        resolved = self.resolve(path)
        if resolved == self._root:
            return "."
        return resolved.relative_to(self._root).as_posix()

    def denied(self, path: str | Path) -> bool:
        """``True`` when any component of the path is a denied directory."""
        resolved = self.resolve(path)
        if not resolved.is_relative_to(self._root):
            return True
        parts = resolved.relative_to(self._root).parts
        return any(part in self._config.denied_directories for part in parts)

    def denied_name(self, name: str) -> bool:
        """``True`` when a bare directory name is on the deny list."""
        return name in self._config.denied_directories
