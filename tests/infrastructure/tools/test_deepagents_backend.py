"""build_backend: FilesystemBackend com raiz real, StateBackend sem ela."""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import FilesystemBackend, StateBackend

from caio_code.config import SandboxConfig, Settings
from caio_code.infrastructure.tools.deepagents_backend import build_backend


def test_real_directory_gets_filesystem_backend(tmp_path: Path) -> None:
    settings = Settings(sandbox=SandboxConfig(root=tmp_path))
    backend = build_backend(settings)
    assert isinstance(backend, FilesystemBackend)


def test_missing_directory_falls_back_to_state_backend(tmp_path: Path) -> None:
    settings = Settings(sandbox=SandboxConfig(root=tmp_path / "does-not-exist"))
    backend = build_backend(settings)
    assert isinstance(backend, StateBackend)
