"""Shared fixtures for CLI tests: workspace, fake secrets, exit-code helper."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

FAKE_SECRET = "sk-FAKE-SECRET-VALUE-do-not-print-0000"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "a.txt").write_text("alpha\n", encoding="utf-8")
    (root / "b.py").write_text("print('beta')\n", encoding="utf-8")
    return root


@pytest.fixture
def fake_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Env credentials that must NEVER appear in any CLI output."""
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_SECRET)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("TYPESAFE_API_KEY", FAKE_SECRET)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://example.invalid/typesafe/v1")
    yield FAKE_SECRET


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the CLI to the offline stub no matter the developer's shell."""
    for name in ("CAIO_CODE_PROVIDER", "CAIO_CODE_MODEL", "CAIO_CODE_WINDOW_TOKENS"):
        monkeypatch.delenv(name, raising=False)
