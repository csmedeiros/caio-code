"""Private helper: tool failures reach the model as text, never as exceptions.

The Python API of each toolset raises typed errors (``ToolError`` and
subclasses). The LangChain wrappers built by ``as_langchain_tools()`` pass
through this guard so a refusal becomes a structured string the model can read
and react to, as required by the foundations skill (section 5).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from caio_code.domain.errors import ToolError


def returns_tool_errors_as_text(func: Callable[..., str]) -> Callable[..., str]:
    """Wrap a tool method so ``ToolError`` is returned as ``error: <message>``."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return func(*args, **kwargs)
        except ToolError as exc:
            return f"error: {exc}"

    return wrapper
