"""Filesystem tools: read, write, edit, list and glob inside the sandbox.

Every result passes through :func:`~caio_code.domain.policy.tool_output.truncate_text`
with the ceilings from :class:`~caio_code.config.ToolOutputConfig`, so
truncation is never silent. Failures raise ``ToolError`` naming the offending
value; the LangChain wrappers convert that into structured text for the model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from caio_code.config import ToolOutputConfig
from caio_code.domain.errors import ToolError
from caio_code.domain.policy.tool_output import TruncationLimits, truncate_text
from caio_code.infrastructure.tools._guard import returns_tool_errors_as_text
from caio_code.infrastructure.tools.sandbox import Sandbox


class FilesystemToolset:
    """File operations confined to a :class:`Sandbox` root."""

    def __init__(self, sandbox: Sandbox, output: ToolOutputConfig) -> None:
        self._sandbox = sandbox
        self._limits = TruncationLimits(max_lines=output.max_lines, max_bytes=output.max_bytes)

    def _finish(self, text: str) -> str:
        truncated, _ = truncate_text(text, self._limits)
        return truncated

    def _resolve_checked(self, path: str | Path) -> Path:
        resolved = self._sandbox.resolve(path)
        if self._sandbox.denied(resolved):
            msg = f"path {str(path)!r} is inside a denied directory"
            raise ToolError(msg)
        return resolved

    def read_file(self, path: str, offset: int | None = None, limit: int | None = None) -> str:
        """Read a text file, optionally a window of lines.

        ``offset`` is the 1-based first line to return; ``limit`` is the maximum
        number of lines. The result is truncated to the configured ceilings.
        """
        resolved = self._resolve_checked(path)
        if not resolved.is_file():
            msg = f"file not found: {str(path)!r}"
            raise ToolError(msg)
        if offset is not None and offset < 1:
            msg = f"offset must be at least 1, got {offset}"
            raise ToolError(msg)
        if limit is not None and limit < 1:
            msg = f"limit must be at least 1, got {limit}"
            raise ToolError(msg)
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            msg = f"cannot read {str(path)!r}: {exc.strerror or exc}"
            raise ToolError(msg) from exc
        if offset is not None or limit is not None:
            lines = content.splitlines()
            start = (offset or 1) - 1
            stop = start + limit if limit is not None else None
            content = "\n".join(lines[start:stop])
        return self._finish(content)

    def write_file(self, path: str, content: str) -> str:
        """Create or overwrite a file, creating parent directories as needed."""
        resolved = self._resolve_checked(path)
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except OSError as exc:
            msg = f"cannot write {str(path)!r}: {exc.strerror or exc}"
            raise ToolError(msg) from exc
        return self._finish(
            f"wrote {len(content.encode('utf-8'))} bytes to {self._sandbox.relative(resolved)}"
        )

    def edit_file(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        """Replace ``old_string`` with ``new_string`` in an existing file.

        Fails with ``ToolError`` when there is no match, or when there are
        multiple matches and ``replace_all`` is false.
        """
        resolved = self._resolve_checked(path)
        if not resolved.is_file():
            msg = f"file not found: {str(path)!r}"
            raise ToolError(msg)
        if old_string == new_string:
            msg = f"old_string and new_string are identical in {str(path)!r}"
            raise ToolError(msg)
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            msg = f"cannot read {str(path)!r}: {exc.strerror or exc}"
            raise ToolError(msg) from exc
        matches = content.count(old_string)
        if matches == 0:
            msg = f"no match for old_string in {str(path)!r}: {old_string!r}"
            raise ToolError(msg)
        if matches > 1 and not replace_all:
            msg = (
                f"old_string matches {matches} times in {str(path)!r}; "
                "add more context or pass replace_all=True"
            )
            raise ToolError(msg)
        updated = content.replace(old_string, new_string) if replace_all else (
            content.replace(old_string, new_string, 1)
        )
        try:
            resolved.write_text(updated, encoding="utf-8")
        except OSError as exc:
            msg = f"cannot write {str(path)!r}: {exc.strerror or exc}"
            raise ToolError(msg) from exc
        return self._finish(
            f"edited {self._sandbox.relative(resolved)}: replaced {matches} occurrence(s)"
        )

    def list_directory(self, path: str) -> str:
        """List one directory; subdirectories carry a trailing ``/``."""
        resolved = self._resolve_checked(path)
        if not resolved.is_dir():
            msg = f"directory not found: {str(path)!r}"
            raise ToolError(msg)
        try:
            entries = sorted(resolved.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            msg = f"cannot list {str(path)!r}: {exc.strerror or exc}"
            raise ToolError(msg) from exc
        lines = [
            f"{entry.name}/" if entry.is_dir() else entry.name
            for entry in entries
            if not (entry.is_dir() and self._sandbox.denied_name(entry.name))
        ]
        return self._finish("\n".join(lines))

    def glob_paths(self, pattern: str, path: str = ".") -> str:
        """Glob ``pattern`` under ``path``, sorted, never following escapes."""
        base = self._resolve_checked(path)
        if not base.is_dir():
            msg = f"directory not found: {str(path)!r}"
            raise ToolError(msg)
        try:
            matches = list(base.glob(pattern))
        except (OSError, ValueError) as exc:
            msg = f"invalid glob pattern {pattern!r}: {exc}"
            raise ToolError(msg) from exc
        kept = sorted(
            self._sandbox.relative(item)
            for item in matches
            if self._sandbox.is_within(item) and not self._sandbox.denied(item)
        )
        if not kept:
            return self._finish(f"no matches for pattern {pattern!r} under {str(path)!r}")
        return self._finish("\n".join(kept))

    def as_langchain_tools(self) -> list[BaseTool]:
        """The five operations as LangChain tools; errors come back as text."""
        specs: list[tuple[str, str, Any, type[BaseModel]]] = [
            ("read_file", _READ_DOC, self.read_file, _ReadFileArgs),
            ("write_file", _WRITE_DOC, self.write_file, _WriteFileArgs),
            ("edit_file", _EDIT_DOC, self.edit_file, _EditFileArgs),
            ("list_directory", _LIST_DOC, self.list_directory, _ListDirectoryArgs),
            ("glob_paths", _GLOB_DOC, self.glob_paths, _GlobPathsArgs),
        ]
        return [
            StructuredTool.from_function(
                func=returns_tool_errors_as_text(func),
                name=name,
                description=doc,
                args_schema=schema,
            )
            for name, doc, func, schema in specs
        ]


_READ_DOC = (
    "Read a text file from the workspace and return its contents. "
    "Use offset (1-based first line) and limit (max lines) for large files. "
    "Output above the configured ceiling is truncated with a visible marker."
)
_WRITE_DOC = (
    "Create or overwrite a file in the workspace with the given content, "
    "creating parent directories as needed. Returns the number of bytes written."
)
_EDIT_DOC = (
    "Replace old_string with new_string in an existing file. old_string must "
    "match exactly once unless replace_all is true; include surrounding lines "
    "to make it unique. Fails when there is no match or multiple matches."
)
_LIST_DOC = "List the entries of one workspace directory; directories end with '/'."
_GLOB_DOC = (
    "Find files by glob pattern (for example '**/*.py') under path, "
    "returning sorted workspace-relative paths."
)


class _ReadFileArgs(BaseModel):
    """Arguments of ``read_file``."""

    path: str = Field(description="Workspace-relative path of the file to read.")
    offset: int | None = Field(
        default=None, description="1-based first line to return; None starts at line 1."
    )
    limit: int | None = Field(
        default=None, description="Maximum number of lines to return; None reads to the end."
    )


class _WriteFileArgs(BaseModel):
    """Arguments of ``write_file``."""

    path: str = Field(description="Workspace-relative path of the file to write.")
    content: str = Field(description="Full new content of the file.")


class _EditFileArgs(BaseModel):
    """Arguments of ``edit_file``."""

    path: str = Field(description="Workspace-relative path of the file to edit.")
    old_string: str = Field(description="Exact text to find in the file.")
    new_string: str = Field(description="Text that replaces old_string.")
    replace_all: bool = Field(
        default=False, description="Replace every occurrence instead of failing on multiples."
    )


class _ListDirectoryArgs(BaseModel):
    """Arguments of ``list_directory``."""

    path: str = Field(description="Workspace-relative directory to list.")


class _GlobPathsArgs(BaseModel):
    """Arguments of ``glob_paths``."""

    pattern: str = Field(description="Glob pattern, for example '**/*.py' or 'src/*.toml'.")
    path: str = Field(default=".", description="Workspace-relative directory to search under.")


__all__ = ["FilesystemToolset"]
