"""``caio-code evaluate``: delegation to the experiment runner, offline only.

These tests must never reach a provider. The runner exists now, so the "module
absent" branch is exercised by hiding it from the importer instead of waiting
for it to be written.
"""

from __future__ import annotations

import builtins
import sys
import types
from typing import Any

import pytest

from caio_code.presentation.cli.main import main

EXIT_OK = 0
EXIT_FAILURE = 1
RUNNER_MODULE = "caio_code.application.experiment.runner"
PACKAGE_MODULE = "caio_code.application.experiment"


def _hide_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import caio_code.application.experiment.runner`` raise ImportError."""
    for name in (RUNNER_MODULE, PACKAGE_MODULE):
        monkeypatch.delitem(sys.modules, name, raising=False)
    real_import = builtins.__import__

    def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith(PACKAGE_MODULE):
            msg = f"blocked for the test: {name}"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)


def test_evaluate_fails_with_typed_error_when_module_absent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _hide_runner(monkeypatch)
    code = main(["evaluate", "--provider", "stub"])
    err = capsys.readouterr().err
    assert code == EXIT_FAILURE
    assert "experiment runner" in err
    assert "not available yet" in err


def test_evaluate_delegates_to_experiment_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_main(**kwargs: Any) -> int:
        captured.update(kwargs)
        return EXIT_OK

    module = types.ModuleType(RUNNER_MODULE)
    module.main = fake_main  # type: ignore[attr-defined]
    package = types.ModuleType(PACKAGE_MODULE)
    package.runner = module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, PACKAGE_MODULE, package)
    monkeypatch.setitem(sys.modules, RUNNER_MODULE, module)

    code = main(
        [
            "evaluate",
            "--provider",
            "stub",
            "--arms",
            "sliding_window,compaction",
            "--cases",
            "3",
            "--repetitions",
            "2",
        ]
    )
    assert code == EXIT_OK
    assert captured["arms"] == ("sliding_window", "compaction")
    assert captured["cases"] == 3
    assert captured["repetitions"] == 2


def test_evaluate_reports_a_non_zero_exit_code_from_the_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = types.ModuleType(RUNNER_MODULE)
    module.main = lambda **kwargs: EXIT_FAILURE  # type: ignore[attr-defined]
    package = types.ModuleType(PACKAGE_MODULE)
    package.runner = module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, PACKAGE_MODULE, package)
    monkeypatch.setitem(sys.modules, RUNNER_MODULE, module)

    assert main(["evaluate", "--provider", "stub"]) == EXIT_FAILURE


def test_evaluate_forwards_the_declared_window_into_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regressão: `--window-tokens` era silenciosamente ignorado porque a CLI
    # construía settings sem repassar a janela. Um run pedido com 32k era
    # moldado e julgado contra os 8k do default, e o número do capítulo saía
    # de uma janela que ninguém declarou.
    captured: dict[str, Any] = {}

    def fake_main(**kwargs: Any) -> int:
        captured.update(kwargs)
        return EXIT_OK

    module = types.ModuleType(RUNNER_MODULE)
    module.main = fake_main  # type: ignore[attr-defined]
    package = types.ModuleType(PACKAGE_MODULE)
    package.runner = module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, PACKAGE_MODULE, package)
    monkeypatch.setitem(sys.modules, RUNNER_MODULE, module)

    code = main(["evaluate", "--provider", "stub", "--window-tokens", "32000"])

    assert code == EXIT_OK
    assert captured["window_tokens"] == 32_000
    assert captured["settings"].window.tokens == 32_000
    assert captured["settings"].provider.provider == "stub"



def test_evaluate_with_variants_routes_to_the_chat_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--variants` troca o experimento congelado pelo chat-replay (v5)."""
    captured: dict[str, Any] = {}

    def fake_main(**kwargs: Any) -> int:
        captured.update(kwargs)
        return EXIT_OK

    monkeypatch.setattr("caio_code.application.evaluation.replay.main", fake_main)

    code = main(
        [
            "evaluate",
            "--provider",
            "stub",
            "--variants",
            "spill,full",
            "--window-tokens",
            "96000",
            "--arms",
            "sliding_window",
        ]
    )

    assert code == EXIT_OK
    assert captured["variants"] == ("spill", "full")
    assert captured["arms"] == ("sliding_window",)
    assert captured["settings"].window.tokens == 96_000


def test_evaluate_with_variants_rejects_an_unknown_variant(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["evaluate", "--provider", "stub", "--variants", "truncated"])
    err = capsys.readouterr().err
    assert code == EXIT_FAILURE
    assert "unknown variants" in err


def test_evaluate_replay_runs_offline_end_to_end(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Um trial de replay completo, do CLI ao relatório, sem provedor real."""
    code = main(
        [
            "evaluate",
            "--provider",
            "stub",
            "--variants",
            "full,spill",
            "--arms",
            "sliding_window",
            "--cases",
            "1",
            "--repetitions",
            "1",
            "--out",
            str(tmp_path),
            "--run-id",
            "cli-replay",
        ]
    )
    out = capsys.readouterr().out

    assert code == EXIT_OK
    assert (tmp_path / "cli-replay" / "results.json").is_file()
    assert (tmp_path / "cli-replay" / "report-comparison.md").is_file()
    assert "sliding_window" in out
