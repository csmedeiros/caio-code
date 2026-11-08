"""FilesystemToolset: round trips, erros tipados, truncamento e tools LangChain."""

from __future__ import annotations

from pathlib import Path

import pytest

from caio_code.config import ToolOutputConfig
from caio_code.domain.errors import ToolError
from caio_code.infrastructure.tools.filesystem import FilesystemToolset
from caio_code.infrastructure.tools.sandbox import Sandbox


@pytest.fixture()
def tools(sandbox: Sandbox, output: ToolOutputConfig) -> FilesystemToolset:
    return FilesystemToolset(sandbox, output)


@pytest.fixture()
def small_tools(sandbox: Sandbox, small_output: ToolOutputConfig) -> FilesystemToolset:
    return FilesystemToolset(sandbox, small_output)


def test_write_read_round_trip(tools: FilesystemToolset, root: Path) -> None:
    confirmation = tools.write_file("a/b.txt", "hello\nworld")
    assert "11 bytes" in confirmation
    assert (root / "a" / "b.txt").read_text(encoding="utf-8") == "hello\nworld"
    assert tools.read_file("a/b.txt") == "hello\nworld"


def test_read_missing_file_raises_naming_the_path(tools: FilesystemToolset) -> None:
    with pytest.raises(ToolError, match=r"missing\.txt"):
        tools.read_file("missing.txt")


def test_read_window_with_offset_and_limit(tools: FilesystemToolset) -> None:
    tools.write_file("lines.txt", "\n".join(f"line{i}" for i in range(1, 11)))
    assert tools.read_file("lines.txt", offset=3, limit=2) == "line3\nline4"


def test_read_rejects_invalid_offset(tools: FilesystemToolset) -> None:
    tools.write_file("f.txt", "x")
    with pytest.raises(ToolError, match="offset must be at least 1, got 0"):
        tools.read_file("f.txt", offset=0)


def test_edit_replaces_single_match(tools: FilesystemToolset) -> None:
    tools.write_file("f.txt", "hello world")
    tools.edit_file("f.txt", "hello", "adeus")
    assert tools.read_file("f.txt") == "adeus world"


def test_edit_without_match_raises_with_the_old_string(tools: FilesystemToolset) -> None:
    tools.write_file("f.txt", "hello")
    with pytest.raises(ToolError, match=r"no match for old_string.*'bye'"):
        tools.edit_file("f.txt", "bye", "x")


def test_edit_with_multiple_matches_raises_unless_replace_all(tools: FilesystemToolset) -> None:
    tools.write_file("f.txt", "aa aa aa")
    with pytest.raises(ToolError, match="matches 3 times"):
        tools.edit_file("f.txt", "aa", "bb")
    tools.edit_file("f.txt", "aa", "bb", replace_all=True)
    assert tools.read_file("f.txt") == "bb bb bb"


def test_denied_directory_is_refused(tools: FilesystemToolset) -> None:
    with pytest.raises(ToolError, match="denied directory"):
        tools.write_file(".git/config", "x")
    with pytest.raises(ToolError, match="denied directory"):
        tools.read_file(".git/config")


def test_escape_is_refused(tools: FilesystemToolset) -> None:
    with pytest.raises(ToolError):
        tools.read_file("../outside.txt")


def test_truncation_marker_present_above_the_ceiling(small_tools: FilesystemToolset) -> None:
    small_tools.write_file("big.txt", "\n".join(f"line-{i}" for i in range(50)))
    result = small_tools.read_file("big.txt")
    assert "output truncated" in result
    assert result.count("\n") < 50


def test_no_truncation_below_the_ceiling(small_tools: FilesystemToolset) -> None:
    small_tools.write_file("small.txt", "one\ntwo")
    assert small_tools.read_file("small.txt") == "one\ntwo"


def test_list_directory_marks_dirs_and_hides_denied(tools: FilesystemToolset, root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("x", encoding="utf-8")
    (root / ".git").mkdir()
    listing = tools.list_directory(".")
    assert "src/" in listing.splitlines()
    assert "main.py" not in listing
    assert ".git" not in listing.splitlines()


def test_list_missing_directory_raises(tools: FilesystemToolset) -> None:
    with pytest.raises(ToolError, match="nope"):
        tools.list_directory("nope")


def test_glob_returns_sorted_relative_paths(tools: FilesystemToolset, root: Path) -> None:
    (root / "b.py").write_text("x", encoding="utf-8")
    (root / "a.py").write_text("x", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "c.py").write_text("x", encoding="utf-8")
    result = tools.glob_paths("*.py")
    assert result.splitlines() == ["a.py", "b.py"]


def test_glob_without_match_says_so(tools: FilesystemToolset) -> None:
    assert "no matches for pattern" in tools.glob_paths("*.rs")


def test_langchain_tools_have_expected_names(tools: FilesystemToolset) -> None:
    names = {tool.name for tool in tools.as_langchain_tools()}
    assert names == {"read_file", "write_file", "edit_file", "list_directory", "glob_paths"}


def test_langchain_tool_returns_error_as_text(tools: FilesystemToolset) -> None:
    by_name = {tool.name: tool for tool in tools.as_langchain_tools()}
    result = by_name["read_file"].invoke({"path": "missing.txt"})
    assert isinstance(result, str)
    assert result.startswith("error:")
    assert "missing.txt" in result


def test_langchain_tool_round_trip(tools: FilesystemToolset) -> None:
    by_name = {tool.name: tool for tool in tools.as_langchain_tools()}
    by_name["write_file"].invoke({"path": "lc.txt", "content": "via tool"})
    assert by_name["read_file"].invoke({"path": "lc.txt"}) == "via tool"
