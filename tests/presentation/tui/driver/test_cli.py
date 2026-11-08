"""Driver CLI: flags, exit codes, script and stdin modes, report files."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from caio_code.presentation.tui.driver.cli import (
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_USAGE,
    main,
    parse_options,
    parse_size,
)
from caio_code.presentation.tui.driver.errors import DriverError
from caio_code.presentation.tui.driver.steps import Send, Wait

pytestmark = pytest.mark.tui


class TestParseSize:
    def test_valid(self) -> None:
        assert parse_size("120x32") == (120, 32)
        assert parse_size("100X30") == (100, 30)

    def test_invalid_raises_driver_error(self) -> None:
        for raw in ("120", "axb", "0x10", "-3x10", "10x20x30"):
            with pytest.raises(DriverError):
                parse_size(raw)


class TestParseOptions:
    def test_scenario_all(self) -> None:
        options = parse_options(["--scenario", "all"])
        assert options.scenarios == ("all",)
        assert options.steps is None

    def test_repeated_scenarios(self) -> None:
        options = parse_options(["--scenario", "smoke", "--scenario", "interrupt"])
        assert options.scenarios == ("smoke", "interrupt")

    def test_script_and_stdin_are_exclusive(self, tmp_path: Path) -> None:
        script = tmp_path / "s.txt"
        script.write_text("wait 1\n", encoding="utf-8")
        with pytest.raises(SystemExit) as excinfo:
            parse_options(["--script", str(script), "--stdin"])
        assert excinfo.value.code == 2

    def test_nothing_requested_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            parse_options([])
        assert excinfo.value.code == 2

    def test_script_is_parsed_into_steps(self, tmp_path: Path) -> None:
        script = tmp_path / "s.txt"
        script.write_text("send hello\nwait 20\n", encoding="utf-8")
        options = parse_options(["--script", str(script)])
        assert options.steps == (Send("hello"), Wait(20))


class TestMain:
    def test_smoke_scenario_exits_zero_and_writes_report(self, tmp_path: Path, capsys) -> None:
        code = main(
            [
                "--scenario",
                "smoke",
                "--reports-dir",
                str(tmp_path),
                "--json",
                str(tmp_path / "out.json"),
                "--markdown",
                str(tmp_path / "out.md"),
            ]
        )
        assert code == EXIT_OK
        report = json.loads((tmp_path / "smoke" / "report.json").read_text(encoding="utf-8"))
        assert report["passed"] is True
        payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert payload[0]["scenario"] == "smoke"
        markdown = (tmp_path / "out.md").read_text(encoding="utf-8")
        assert "# driver report: smoke - PASSED" in markdown
        out = capsys.readouterr().out
        assert "== scenario smoke: PASSED" in out
        assert "[passed]" in out

    def test_script_mode_runs_send_assert_snapshot_todo(self, tmp_path: Path) -> None:
        script = tmp_path / "agent.txt"
        script.write_text(
            "\n".join(
                (
                    "# an AI agent driving the TUI turn by turn",
                    "send fix the bug",
                    "wait 50",
                    "assert-text Patched the policy",
                    "assert-todo count=3 completed=1 in_progress=1",
                    "snapshot after-send",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        code = main(["--script", str(script), "--reports-dir", str(tmp_path / "reports")])
        assert code == EXIT_OK
        assert (tmp_path / "reports" / "script" / "004-after-send.svg").is_file()
        assert (tmp_path / "reports" / "script" / "004-after-send.txt").is_file()

    def test_stdin_mode(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("snapshot from-stdin\n"))
        code = main(["--stdin", "--reports-dir", str(tmp_path)])
        assert code == EXIT_OK
        assert (tmp_path / "script" / "000-from-stdin.svg").is_file()

    def test_unknown_scenario_exits_usage(self, tmp_path: Path) -> None:
        assert main(["--scenario", "nope", "--reports-dir", str(tmp_path)]) == EXIT_USAGE

    def test_unknown_script_verb_exits_usage(self, tmp_path: Path) -> None:
        script = tmp_path / "bad.txt"
        script.write_text("frobnicate now\n", encoding="utf-8")
        assert main(["--script", str(script), "--reports-dir", str(tmp_path)]) == EXIT_USAGE

    def test_failing_assertion_exits_one(self, tmp_path: Path) -> None:
        script = tmp_path / "fail.txt"
        script.write_text("assert-text this-will-never-appear\n", encoding="utf-8")
        code = main(
            ["--script", str(script), "--reports-dir", str(tmp_path), "--continue-on-error"]
        )
        assert code == EXIT_FAILURE
        report = json.loads((tmp_path / "script" / "report.json").read_text(encoding="utf-8"))
        assert report["passed"] is False
        assert len(report["failures"]) == 1
