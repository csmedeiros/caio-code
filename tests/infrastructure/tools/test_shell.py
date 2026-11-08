"""ShellToolset: recusa, timeout, exit não zero e backend deepagents."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from deepagents.backends import LocalShellBackend

from caio_code.config import SandboxConfig, Settings, ToolOutputConfig
from caio_code.domain.errors import ToolError
from caio_code.infrastructure.tools.sandbox import Sandbox
from caio_code.infrastructure.tools.shell import ShellToolset, shell_backend


@pytest.fixture()
def shell(sandbox: Sandbox, sandbox_config: SandboxConfig, output: ToolOutputConfig) -> ShellToolset:
    return ShellToolset(sandbox, sandbox_config, output)


def disabled_shell(root: Path) -> ShellToolset:
    config = SandboxConfig(root=root, allow_execute=False)
    return ShellToolset(Sandbox(config), config, ToolOutputConfig())


def test_refusal_when_execution_disabled(root: Path) -> None:
    result = disabled_shell(root).execute(["echo", "hi"])
    assert result.startswith("refused:")
    assert "allow_execute=False" in result
    assert "echo" in result


def test_refusal_through_langchain_tool(root: Path) -> None:
    tool = disabled_shell(root).as_langchain_tools()[0]
    result = tool.invoke({"command": ["echo", "hi"]})
    assert isinstance(result, str)
    assert result.startswith("refused:")


def test_execute_returns_stdout(shell: ShellToolset) -> None:
    result = shell.execute([sys.executable, "-c", "print('hi')"])
    assert "hi" in result


def test_execute_runs_in_sandbox_root(shell: ShellToolset, root: Path) -> None:
    result = shell.execute([sys.executable, "-c", "import os; print(os.getcwd())"])
    assert Path(result.strip()).resolve() == root.resolve()


def test_nonzero_exit_is_a_structured_string(shell: ShellToolset) -> None:
    result = shell.execute([sys.executable, "-c", "raise SystemExit(3)"])
    assert "exit code 3" in result


def test_stderr_is_included(shell: ShellToolset) -> None:
    result = shell.execute([sys.executable, "-c", "import sys; sys.stderr.write('boom')"])
    assert "boom" in result


def test_timeout_is_reported_not_raised(shell: ShellToolset) -> None:
    result = shell.execute(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout_seconds=0.2
    )
    assert "timed out after 0.2s" in result


def test_missing_executable_is_reported(shell: ShellToolset) -> None:
    result = shell.execute(["definitely-not-an-executable-xyz"])
    assert "executable not found" in result
    assert "definitely-not-an-executable-xyz" in result


def test_empty_command_raises_tool_error(shell: ShellToolset) -> None:
    with pytest.raises(ToolError, match="non-empty argv list"):
        shell.execute([])


def test_negative_timeout_raises_tool_error(shell: ShellToolset) -> None:
    with pytest.raises(ToolError, match="timeout_seconds must be positive, got -1"):
        shell.execute([sys.executable, "-c", "pass"], timeout_seconds=-1.0)


def test_output_is_truncated(shell: ShellToolset, sandbox_config: SandboxConfig) -> None:
    small = ShellToolset(
        Sandbox(sandbox_config), sandbox_config, ToolOutputConfig(max_lines=4, max_bytes=120)
    )
    result = small.execute([sys.executable, "-c", "print('\\n'.join(str(i) for i in range(50)))"])
    assert "output truncated" in result


def test_execute_tool_schema(shell: ShellToolset) -> None:
    tools = shell.as_langchain_tools()
    assert [tool.name for tool in tools] == ["execute"]
    result = tools[0].invoke({"command": [sys.executable, "-c", "print('ok')"]})
    assert "ok" in result


def test_shell_backend_none_when_disabled(root: Path) -> None:
    settings = Settings(sandbox=SandboxConfig(root=root, allow_execute=False))
    assert shell_backend(settings) is None


def test_shell_backend_builds_when_enabled(root: Path) -> None:
    settings = Settings(sandbox=SandboxConfig(root=root, allow_execute=True))
    backend = shell_backend(settings)
    assert isinstance(backend, LocalShellBackend)
