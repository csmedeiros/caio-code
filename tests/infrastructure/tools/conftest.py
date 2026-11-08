"""Fixtures compartilhadas dos testes de tools: raiz em tmp_path, configs."""

from __future__ import annotations

from pathlib import Path

import pytest

from caio_code.config import SandboxConfig, ToolOutputConfig
from caio_code.infrastructure.tools.sandbox import Sandbox


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture()
def sandbox(root: Path) -> Sandbox:
    return Sandbox(SandboxConfig(root=root))


@pytest.fixture()
def sandbox_config(root: Path) -> SandboxConfig:
    return SandboxConfig(root=root)


@pytest.fixture()
def output() -> ToolOutputConfig:
    return ToolOutputConfig()


@pytest.fixture()
def small_output() -> ToolOutputConfig:
    return ToolOutputConfig(max_lines=4, max_bytes=120)
