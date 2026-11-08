"""Shell execution tool: argv lists only, never ``shell=True``.

Commands run with ``subprocess.run`` (no shell, no string interpolation),
``cwd`` fixed to the sandbox root, and the timeout from
:class:`~caio_code.config.SandboxConfig`. Combined output passes through
``truncate_text``. A non-zero exit or a timeout is reported as a structured
string — the model sees the failure, it never receives an exception.
"""

from __future__ import annotations

import subprocess

from deepagents.backends import LocalShellBackend
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from caio_code.config import SandboxConfig, Settings, ToolOutputConfig
from caio_code.domain.errors import ToolError
from caio_code.domain.policy.tool_output import TruncationLimits, truncate_text
from caio_code.infrastructure.tools._guard import returns_tool_errors_as_text
from caio_code.infrastructure.tools.sandbox import Sandbox

REFUSAL_TEMPLATE = (
    "refused: shell execution is disabled (allow_execute=False); command={command!r}"
)


class ShellToolset:
    """Runs argv lists inside the sandbox root."""

    def __init__(
        self,
        sandbox: Sandbox,
        config: SandboxConfig,
        output: ToolOutputConfig,
    ) -> None:
        self._sandbox = sandbox
        self._config = config
        self._limits = TruncationLimits(max_lines=output.max_lines, max_bytes=output.max_bytes)

    def execute(self, command: list[str], timeout_seconds: float | None = None) -> str:
        """Run ``command`` (argv list) and return combined, truncated output.

        A disabled sandbox, a timeout, a missing executable and a non-zero exit
        all come back as readable strings, never as exceptions.
        """
        if not self._config.allow_execute:
            return REFUSAL_TEMPLATE.format(command=command)
        if not command:
            msg = "command must be a non-empty argv list, got []"
            raise ToolError(msg)
        if timeout_seconds is not None and timeout_seconds <= 0:
            msg = f"timeout_seconds must be positive, got {timeout_seconds}"
            raise ToolError(msg)
        timeout = (
            timeout_seconds if timeout_seconds is not None else self._config.execute_timeout_seconds
        )
        try:
            completed = subprocess.run(
                command,
                shell=False,
                cwd=self._sandbox.root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._finish(
                f"command timed out after {timeout}s: {command!r}"
            )
        except FileNotFoundError:
            return self._finish(f"executable not found: {command[0]!r}")
        except OSError as exc:
            return self._finish(f"cannot execute {command!r}: {exc.strerror or exc}")
        output = completed.stdout
        if completed.stderr:
            output = f"{output}\n{completed.stderr}" if output else completed.stderr
        if completed.returncode != 0:
            header = f"exit code {completed.returncode} for {command!r}"
            output = f"{header}\n{output}" if output else header
        return self._finish(output)

    def _finish(self, text: str) -> str:
        truncated, _ = truncate_text(text, self._limits)
        return truncated

    def as_langchain_tools(self) -> list[BaseTool]:
        """One ``execute`` tool; refusals and failures come back as text."""
        return [
            StructuredTool.from_function(
                func=returns_tool_errors_as_text(self.execute),
                name="execute",
                description=_EXECUTE_DOC,
                args_schema=_ExecuteArgs,
            )
        ]


_EXECUTE_DOC = (
    "Run a shell command in the workspace root and return its combined "
    "stdout/stderr. The command is an argv list (for example ['git', 'status']), "
    "never a shell string. Non-zero exits and timeouts are reported in the "
    "output text. Execution may be disabled by policy, in which case the tool "
    "returns a refusal."
)


class _ExecuteArgs(BaseModel):
    """Arguments of ``execute``."""

    command: list[str] = Field(description="Argv list, for example ['python', '-m', 'pytest'].")
    timeout_seconds: float | None = Field(
        default=None,
        description="Optional per-call timeout; defaults to the configured sandbox timeout.",
    )


def shell_backend(settings: Settings) -> LocalShellBackend | None:
    """deepagents shell backend rooted at the sandbox, or ``None`` if disabled."""
    if not settings.sandbox.allow_execute:
        return None
    return LocalShellBackend(
        root_dir=settings.sandbox.root,
        virtual_mode=True,
        timeout=int(settings.sandbox.execute_timeout_seconds),
        max_output_bytes=settings.tool_output.max_bytes,
    )


__all__ = ["REFUSAL_TEMPLATE", "ShellToolset", "shell_backend"]
