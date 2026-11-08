"""Sandbox: confinamento de caminhos à raiz."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from caio_code.config import SandboxConfig
from caio_code.domain.errors import SandboxEscapeError
from caio_code.infrastructure.tools.sandbox import Sandbox


def test_resolve_keeps_path_inside_root(root: Path, sandbox: Sandbox) -> None:
    resolved = sandbox.resolve("src/main.py")
    assert resolved == (root / "src" / "main.py").resolve()


def test_resolve_root_itself(root: Path, sandbox: Sandbox) -> None:
    assert sandbox.resolve(".") == root.resolve()


def test_dotdot_escape_raises_sandbox_escape_error(root: Path, sandbox: Sandbox) -> None:
    with pytest.raises(SandboxEscapeError, match="escapes sandbox root"):
        sandbox.resolve("../outside.txt")


def test_nested_dotdot_escape_raises(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxEscapeError):
        sandbox.resolve("a/../../..")


def test_absolute_path_outside_root_raises(sandbox: Sandbox) -> None:
    with pytest.raises(SandboxEscapeError, match="/etc/passwd"):
        sandbox.resolve("/etc/passwd")


def test_absolute_path_inside_root_is_allowed(root: Path, sandbox: Sandbox) -> None:
    inside = root / "inner.txt"
    inside.write_text("x", encoding="utf-8")
    assert sandbox.resolve(str(inside)) == inside.resolve()


def test_symlink_to_outside_file_raises(tmp_path: Path, root: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    os.symlink(secret, root / "link.txt")
    sandbox = Sandbox(SandboxConfig(root=root))
    with pytest.raises(SandboxEscapeError, match=r"link\.txt"):
        sandbox.resolve("link.txt")


def test_symlinked_parent_directory_escape_raises(tmp_path: Path, root: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("data", encoding="utf-8")
    os.symlink(outside, root / "tunnel")
    sandbox = Sandbox(SandboxConfig(root=root))
    with pytest.raises(SandboxEscapeError, match="tunnel"):
        sandbox.resolve("tunnel/f.txt")


def test_is_within_reports_escape_without_raising(sandbox: Sandbox) -> None:
    assert sandbox.is_within("../outside.txt") is False
    assert sandbox.is_within("/etc/passwd") is False
    assert sandbox.is_within("src/main.py") is True


def test_relative_of_root_is_dot(sandbox: Sandbox) -> None:
    assert sandbox.relative(".") == "."


def test_relative_returns_posix_path(root: Path, sandbox: Sandbox) -> None:
    assert sandbox.relative(root / "a" / "b.txt") == "a/b.txt"


def test_denied_flags_denied_directory(sandbox: Sandbox) -> None:
    assert sandbox.denied(".git/config") is True
    assert sandbox.denied("src/.venv/lib") is True


def test_denied_allows_normal_path(sandbox: Sandbox) -> None:
    assert sandbox.denied("src/main.py") is False


def test_denied_name_matches_bare_component(sandbox: Sandbox) -> None:
    assert sandbox.denied_name("node_modules") is True
    assert sandbox.denied_name("src") is False
