"""``caio-code run`` headless: exit code, stdout block, JSON record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caio_code.presentation.cli.main import main

EXIT_OK = 0


def test_run_stub_exits_zero_with_metrics(
    workspace: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "run",
            "--task",
            "list the files in this repo and summarise what they do",
            "--provider",
            "stub",
            "--root",
            str(workspace),
        ]
    )
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "metrics:" in out
    assert "status: completed" in out
    assert "tokens_in:" in out
    assert "cache_hit:" in out
    assert "cost_usd:" in out
    assert "context: sliding_window" in out


def test_run_json_writes_a_parseable_record(workspace: Path, tmp_path: Path) -> None:
    out_file = tmp_path / "record.json"
    code = main(
        [
            "run",
            "--task",
            "list files",
            "--provider",
            "stub",
            "--root",
            str(workspace),
            "--json",
            str(out_file),
        ]
    )
    assert code == EXIT_OK
    record = json.loads(out_file.read_text(encoding="utf-8"))
    assert record["status"] == "completed"
    assert record["usage"]["input_tokens"] > 0
    assert record["context"]["pipeline"] == "sliding_window"
    assert record["transcript"]
    assert record["final_text"]


def test_run_honours_policy_and_window(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "run",
            "--task",
            "list files",
            "--provider",
            "stub",
            "--root",
            str(workspace),
            "--policy",
            "baseline",
            "--window-tokens",
            "4000",
        ]
    )
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "context: baseline_full_history" in out
    assert "/ 4000 budget" in out
