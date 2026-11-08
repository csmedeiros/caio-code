"""``caio-code doctor``: names only, never secret values; provider health."""

from __future__ import annotations

import json

import pytest

from caio_code.presentation.cli.main import main

EXIT_OK = 0
EXIT_UNUSABLE = 1


def test_doctor_json_exits_zero_and_hides_secret_values(
    fake_credentials: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")  # do not pick up a repo .env
    code = main(["doctor", "--json"])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    report = json.loads(out)
    assert fake_credentials not in out
    assert report["env_present"]["OPENAI_API_KEY"] is True
    assert report["providers"]["stub"]["usable"] is True
    assert report["providers"]["openai_compatible"]["usable"] is True
    assert "typesafe" not in report["providers"]
    assert report["token_counter"].startswith("char_proxy")
    assert "input_per_million_usd" in report["price"]
    assert "cases" in report["dataset"]


def test_doctor_reports_the_decision_model_section(
    fake_credentials: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    code = main(["doctor", "--json"])
    assert code == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    decision = report["decision"]
    assert decision["api_key_present"] is True  # TYPESAFE_API_KEY set by the fixture
    assert decision["provider"] == "typesafe"  # default when the key is present
    assert decision["model"] == "jev-latest"
    assert decision["base_url"].startswith("https://")
    assert decision["timeout_seconds"] > 0
    assert decision["sdk_importable"] is True
    assert decision["selection_scorer"] in {"lexical", "model", "decision"}
    assert decision["usable"] is True
    assert fake_credentials not in json.dumps(report)


def test_doctor_fails_when_the_decision_provider_lacks_a_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("CAIO_CODE_DECISION_PROVIDER", "typesafe")
    code = main(["doctor", "--json"])
    assert code == EXIT_UNUSABLE
    report = json.loads(capsys.readouterr().out)
    assert report["decision"]["provider"] == "typesafe"
    assert report["decision"]["api_key_present"] is False
    assert report["decision"]["usable"] is False


def test_doctor_human_readable_lists_env_names(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    code = main(["doctor"])
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "OPENAI_API_KEY" in out
    assert "providers:" in out
    assert "decision model:" in out
    assert "token counter:" in out


def test_doctor_fails_when_requested_provider_lacks_credentials(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    code = main(["doctor", "--json", "--provider", "openai_compatible"])
    assert code == EXIT_UNUSABLE
    report = json.loads(capsys.readouterr().out)
    assert report["providers"]["openai_compatible"]["usable"] is False
