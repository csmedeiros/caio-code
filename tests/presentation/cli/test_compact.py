"""``caio-code compact``: one anchored compaction of a stored transcript."""

from __future__ import annotations

from pathlib import Path

import pytest

from caio_code.domain.conversation.messages import Message, Role, Transcript
from caio_code.infrastructure.persistence.codec import transcript_to_json
from caio_code.presentation.cli.main import main

EXIT_OK = 0
MESSAGE_COUNT = 12
FILLER_WORDS = 40


def _stored_transcript(path: Path) -> None:
    messages = [
        Message(
            id=f"m-{index:03d}",
            role=Role.USER if index % 2 == 0 else Role.ASSISTANT,
            text=f"message {index}: " + " ".join(f"word{w}" for w in range(FILLER_WORDS)),
        )
        for index in range(MESSAGE_COUNT)
    ]
    path.write_text(
        transcript_to_json(Transcript.of(messages), "session-compact-test"),
        encoding="utf-8",
    )


def test_compact_prints_anchored_summary_and_cost(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transcript_file = tmp_path / "transcript.json"
    _stored_transcript(transcript_file)
    code = main(
        [
            "compact",
            "--transcript",
            str(transcript_file),
            "--keep-tokens",
            "20",
            "--provider",
            "stub",
        ]
    )
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "## Objective" in out
    assert "## Next Move" in out
    assert "## Relevant Files" in out
    assert "well_formed: True" in out
    assert "cost_usd:" in out


def test_compact_writes_out_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    transcript_file = tmp_path / "transcript.json"
    _stored_transcript(transcript_file)
    out_file = tmp_path / "summary.txt"
    code = main(
        [
            "compact",
            "--transcript",
            str(transcript_file),
            "--keep-tokens",
            "20",
            "--provider",
            "stub",
            "--out",
            str(out_file),
        ]
    )
    assert code == EXIT_OK
    assert "## Objective" in out_file.read_text(encoding="utf-8")


def test_compact_missing_file_is_a_typed_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["compact", "--transcript", str(tmp_path / "absent.json"), "--provider", "stub"]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "transcript file not found" in err
    assert "absent.json" in err
