"""SearchToolset: grep e find_files com stdlib, tetos e exclusões."""

from __future__ import annotations

import pytest

from caio_code.config import ToolOutputConfig
from caio_code.domain.errors import ToolError
from caio_code.infrastructure.tools.sandbox import Sandbox
from caio_code.infrastructure.tools.search import SearchToolset


@pytest.fixture()
def search(sandbox: Sandbox, output: ToolOutputConfig) -> SearchToolset:
    return SearchToolset(sandbox, output, max_results=100)


def test_grep_finds_matches_with_path_and_line(search: SearchToolset, sandbox: Sandbox) -> None:
    (sandbox.root / "a.py").write_text("alpha\nbeta\n", encoding="utf-8")
    result = search.grep("bet")
    assert result == "a.py:2:beta"


def test_grep_respects_file_glob(search: SearchToolset, sandbox: Sandbox) -> None:
    (sandbox.root / "a.py").write_text("needle\n", encoding="utf-8")
    (sandbox.root / "a.txt").write_text("needle\n", encoding="utf-8")
    result = search.grep("needle", file_glob="*.py")
    assert result == "a.py:1:needle"


def test_grep_skips_binary_files(search: SearchToolset, sandbox: Sandbox) -> None:
    (sandbox.root / "blob.bin").write_bytes(b"needle\x00binary")
    (sandbox.root / "a.txt").write_text("needle\n", encoding="utf-8")
    result = search.grep("needle")
    assert "blob.bin" not in result
    assert "a.txt:1:needle" in result


def test_grep_skips_denied_directories(search: SearchToolset, sandbox: Sandbox) -> None:
    denied = sandbox.root / ".git"
    denied.mkdir()
    (denied / "config").write_text("needle\n", encoding="utf-8")
    (sandbox.root / "a.txt").write_text("needle\n", encoding="utf-8")
    result = search.grep("needle")
    assert ".git" not in result
    assert "a.txt:1:needle" in result


def test_grep_inside_denied_directory_is_refused(search: SearchToolset, sandbox: Sandbox) -> None:
    (sandbox.root / ".git").mkdir()
    with pytest.raises(ToolError, match="denied directory"):
        search.grep("needle", path=".git")


def test_grep_stops_at_max_results(sandbox: Sandbox, output: ToolOutputConfig) -> None:
    limited = SearchToolset(sandbox, output, max_results=2)
    (sandbox.root / "a.txt").write_text("n\nn\nn\n", encoding="utf-8")
    result = limited.grep("n")
    lines = result.splitlines()
    assert lines[:2] == ["a.txt:1:n", "a.txt:2:n"]
    assert "result limit reached (2 matches)" in lines[2]


def test_grep_invalid_regex_raises_naming_the_pattern(search: SearchToolset) -> None:
    with pytest.raises(ToolError, match=r"invalid regex '\('"):
        search.grep("(")


def test_grep_without_match_says_so(search: SearchToolset) -> None:
    assert "no matches for pattern" in search.grep("absent")


def test_find_files_matches_name_and_relative_path(
    search: SearchToolset, sandbox: Sandbox
) -> None:
    (sandbox.root / "src").mkdir()
    (sandbox.root / "src" / "main.py").write_text("x", encoding="utf-8")
    (sandbox.root / "top.py").write_text("x", encoding="utf-8")
    result = search.find_files("*.py")
    assert result.splitlines() == ["src/main.py", "top.py"]


def test_find_files_skips_denied_directories(search: SearchToolset, sandbox: Sandbox) -> None:
    denied = sandbox.root / "node_modules"
    denied.mkdir()
    (denied / "dep.js").write_text("x", encoding="utf-8")
    (sandbox.root / "app.js").write_text("x", encoding="utf-8")
    assert search.find_files("*.js") == "app.js"


def test_find_files_without_match_says_so(search: SearchToolset) -> None:
    assert "no files match pattern" in search.find_files("*.rs")


def test_langchain_tools_have_expected_names(search: SearchToolset) -> None:
    names = [tool.name for tool in search.as_langchain_tools()]
    assert names == ["grep", "find_files"]


def test_langchain_grep_returns_error_as_text(search: SearchToolset) -> None:
    tool = search.as_langchain_tools()[0]
    result = tool.invoke({"pattern": "("})
    assert isinstance(result, str)
    assert result.startswith("error: invalid regex")


def test_non_positive_max_results_is_refused(sandbox: Sandbox, output: ToolOutputConfig) -> None:
    with pytest.raises(ToolError, match="max_results must be positive, got 0"):
        SearchToolset(sandbox, output, max_results=0)
