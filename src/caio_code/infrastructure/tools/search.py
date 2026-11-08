"""Search tools: grep and find implemented with the standard library only.

No ripgrep dependency: ``re`` plus ``pathlib``/``fnmatch``. The walk prunes
denied directories, skips binary files (a NUL byte in the head of the file),
stops at ``max_results`` and passes the result through ``truncate_text``.
Iteration order is always explicit (``sorted``) so the output is deterministic.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from caio_code.config import ToolOutputConfig
from caio_code.domain.errors import ToolError
from caio_code.domain.policy.tool_output import TruncationLimits, truncate_text
from caio_code.infrastructure.tools._guard import returns_tool_errors_as_text
from caio_code.infrastructure.tools.sandbox import Sandbox

BINARY_PROBE_BYTES = 8_192
"""How many leading bytes are inspected to classify a file as binary."""

MAX_LINE_CHARS = 400
"""Grep prints at most this many characters of a matching line."""


class SearchToolset:
    """Content and filename search inside the sandbox."""

    def __init__(self, sandbox: Sandbox, output: ToolOutputConfig, max_results: int) -> None:
        if max_results <= 0:
            msg = f"max_results must be positive, got {max_results}"
            raise ToolError(msg)
        self._sandbox = sandbox
        self._limits = TruncationLimits(max_lines=output.max_lines, max_bytes=output.max_bytes)
        self._max_results = max_results

    def grep(self, pattern: str, path: str = ".", file_glob: str | None = None) -> str:
        """Search file contents for a regular expression.

        Returns ``relpath:lineno:line`` for each match, up to ``max_results``.
        ``file_glob`` optionally filters which files are searched (for example
        ``*.py``). Binary files and denied directories are skipped.
        """
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            msg = f"invalid regex {pattern!r}: {exc}"
            raise ToolError(msg) from exc
        base = self._resolve_dir(path)
        lines: list[str] = []
        hits = 0
        for file in self._walk_files(base):
            if file_glob is not None and not fnmatch.fnmatch(file.name, file_glob):
                continue
            for lineno, line in self._matching_lines(file, regex):
                shown = line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + " …"
                lines.append(f"{self._sandbox.relative(file)}:{lineno}:{shown}")
                hits += 1
                if hits >= self._max_results:
                    lines.append(
                        f"result limit reached ({self._max_results} matches); "
                        "narrow the pattern or the path"
                    )
                    return self._finish("\n".join(lines))
        if not lines:
            return self._finish(f"no matches for pattern {pattern!r} under {str(path)!r}")
        return self._finish("\n".join(lines))

    def find_files(self, pattern: str, path: str = ".") -> str:
        """Find files whose name or workspace-relative path matches a glob."""
        base = self._resolve_dir(path)
        kept: list[str] = []
        limited = False
        for file in self._walk_files(base):
            relative = self._sandbox.relative(file)
            if fnmatch.fnmatch(file.name, pattern) or fnmatch.fnmatch(relative, pattern):
                kept.append(relative)
                if len(kept) >= self._max_results:
                    limited = True
                    break
        if not kept:
            return self._finish(f"no files match pattern {pattern!r} under {str(path)!r}")
        lines = sorted(kept)
        if limited:
            lines.append(
                f"result limit reached ({self._max_results} files); "
                "narrow the pattern or the path"
            )
        return self._finish("\n".join(lines))

    def _resolve_dir(self, path: str) -> Path:
        base = self._sandbox.resolve(path)
        if self._sandbox.denied(base):
            msg = f"path {path!r} is inside a denied directory"
            raise ToolError(msg)
        if not base.is_dir():
            msg = f"directory not found: {path!r}"
            raise ToolError(msg)
        return base

    def _walk_files(self, base: Path) -> list[Path]:
        """Regular files under ``base``, sorted, pruning denied directories."""
        found: list[Path] = []
        stack = [base]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir(), key=lambda item: item.as_posix())
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if self._sandbox.denied_name(entry.name):
                        continue
                    stack.append(entry)
                elif entry.is_file():
                    found.append(entry)
        return sorted(found, key=lambda item: item.as_posix())

    def _matching_lines(self, file: Path, regex: re.Pattern[str]) -> list[tuple[int, str]]:
        try:
            with file.open("rb") as handle:
                head = handle.read(BINARY_PROBE_BYTES)
            if b"\0" in head:
                return []
            content = file.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            return []
        return [
            (number, line)
            for number, line in enumerate(content.splitlines(), start=1)
            if regex.search(line)
        ]

    def _finish(self, text: str) -> str:
        truncated, _ = truncate_text(text, self._limits)
        return truncated

    def as_langchain_tools(self) -> list[BaseTool]:
        """``grep`` and ``find_files`` as LangChain tools; errors come back as text."""
        return [
            StructuredTool.from_function(
                func=returns_tool_errors_as_text(self.grep),
                name="grep",
                description=_GREP_DOC,
                args_schema=_GrepArgs,
            ),
            StructuredTool.from_function(
                func=returns_tool_errors_as_text(self.find_files),
                name="find_files",
                description=_FIND_DOC,
                args_schema=_FindFilesArgs,
            ),
        ]


_GREP_DOC = (
    "Search file contents in the workspace with a Python regular expression. "
    "Returns 'path:line:text' for each match, up to the configured result "
    "limit. Optionally restrict to files matching file_glob (for example "
    "'*.py'). Binary files and directories like .git are skipped."
)
_FIND_DOC = (
    "Find files in the workspace whose name or relative path matches a glob "
    "pattern (for example '*.py' or 'src/*'). Returns sorted relative paths, "
    "up to the configured result limit."
)


class _GrepArgs(BaseModel):
    """Arguments of ``grep``."""

    pattern: str = Field(description="Python regular expression to search for in file contents.")
    path: str = Field(default=".", description="Workspace-relative directory to search under.")
    file_glob: str | None = Field(
        default=None, description="Optional filename filter, for example '*.py'."
    )


class _FindFilesArgs(BaseModel):
    """Arguments of ``find_files``."""

    pattern: str = Field(description="Glob pattern matched against name and relative path.")
    path: str = Field(default=".", description="Workspace-relative directory to search under.")


__all__ = ["BINARY_PROBE_BYTES", "MAX_LINE_CHARS", "SearchToolset"]
