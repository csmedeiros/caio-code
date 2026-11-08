"""Offline tests for tracing configuration. No key is ever required or printed."""

from __future__ import annotations

import os

import pytest

from caio_code.config import EndpointConfig, Settings
from caio_code.infrastructure.observability.langsmith import (
    API_KEY_ENV_VAR,
    PROJECT_ENV_VAR,
    TRACING_ENV_VAR,
    configure_tracing,
    tracing_disabled,
)


def _settings(api_key: str = "", project: str = "caio-code") -> Settings:
    return Settings(
        endpoints=EndpointConfig(langsmith_api_key=api_key, langsmith_project=project)
    )


def test_tracing_disabled_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TRACING_ENV_VAR, raising=False)
    assert configure_tracing(_settings()) is False
    assert os.environ[TRACING_ENV_VAR] == "false"


def test_tracing_enabled_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TRACING_ENV_VAR, raising=False)
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    settings = _settings(api_key="secret-value", project="thesis")
    assert configure_tracing(settings) is True
    assert os.environ[TRACING_ENV_VAR] == "true"
    assert os.environ[API_KEY_ENV_VAR] == "secret-value"
    assert os.environ[PROJECT_ENV_VAR] == "thesis"


def test_configure_tracing_never_prints_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(TRACING_ENV_VAR, raising=False)
    configure_tracing(_settings(api_key="super-secret"))
    captured = capsys.readouterr()
    assert "super-secret" not in captured.out + captured.err


def test_tracing_disabled_context_manager() -> None:
    from langsmith import utils as langsmith_utils

    with tracing_disabled():
        assert langsmith_utils.tracing_is_enabled() is False
    # Outside the block the helper simply reports the ambient state again.
    langsmith_utils.tracing_is_enabled()
