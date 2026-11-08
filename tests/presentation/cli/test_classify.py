"""``caio-code classify``: the offline decision-model smoke check."""

from __future__ import annotations

import pytest

from caio_code.presentation.cli.main import main

EXIT_OK = 0
EXIT_FAILURE = 1


def test_classify_with_the_stub_provider_exits_zero_and_prints_answers(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")  # do not pick up a repo .env
    code = main(
        [
            "classify",
            "--provider",
            "stub",
            "--state",
            "the build fails with a KeyError in the compaction service",
            "--noul",
            "urgent=Does this state describe a failure?",
            "--choice",
            "area=Which area?|domain=pure rules|infra=adapters",
            "--score",
            "severity=How severe?|low|high",
        ]
    )
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "urgent [noul]: p(yes)=" in out
    assert "area [choice]:" in out
    assert "confidence=" in out
    assert "severity [score]:" in out
    assert "model: stub" in out
    assert "usage: input_tokens=" in out


def test_classify_is_deterministic_with_the_stub_provider(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    argv = [
        "classify",
        "--provider",
        "stub",
        "--state",
        "same state",
        "--noul",
        "q=same question?",
    ]
    assert main(argv) == EXIT_OK
    first = capsys.readouterr().out
    assert main(argv) == EXIT_OK
    assert capsys.readouterr().out == first


def test_classify_never_prints_the_secret(
    fake_credentials: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    code = main(["classify", "--provider", "stub", "--state", "s", "--noul", "q=relevant?"])
    assert code == EXIT_OK
    captured = capsys.readouterr()
    assert fake_credentials not in captured.out
    assert fake_credentials not in captured.err


def test_classify_without_questions_fails(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    code = main(["classify", "--provider", "stub", "--state", "s"])
    assert code == EXIT_FAILURE
    assert "at least one question" in capsys.readouterr().err


def test_classify_typesafe_without_a_key_names_the_env_var(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    code = main(["classify", "--provider", "typesafe", "--state", "s", "--noul", "q=relevant?"])
    assert code == EXIT_FAILURE
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err


def test_classify_rejects_a_malformed_choice(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    code = main(
        ["classify", "--provider", "stub", "--state", "s", "--choice", "c=Which?|a=first|b"]
    )
    assert code == EXIT_FAILURE
    assert "label=description" in capsys.readouterr().err


def test_classify_rejects_a_choice_with_a_single_label(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    code = main(
        ["classify", "--provider", "stub", "--state", "s", "--choice", "c=Which?|a=first"]
    )
    assert code == EXIT_FAILURE
    assert "at least 2 labels" in capsys.readouterr().err
