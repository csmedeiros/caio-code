"""System prompt of the agent, assembled from the resolved configuration.

The prompt states the role, the tool surface, the todo discipline the harnesses
this prototype mirrors enforce, the rule that answers carry exact paths and
values, and the context-management contract: the transcript may be summarized,
and the summary's "Next Move" and "Relevant Files" sections are authoritative.

Every number in the prompt arrives as a parameter (``window_tokens``); nothing
here re-derives a limit that belongs in :mod:`caio_code.config`.
"""

from __future__ import annotations

from caio_code.domain.conversation.summary import SUMMARY_MESSAGE_PREFIX

TOOL_NAMES: tuple[str, ...] = (
    "read_file",
    "write_file",
    "edit_file",
    "list_directory",
    "glob_paths",
    "grep",
    "find_files",
    "execute",
    "write_todos",
)
"""Tools the prompt advertises; the graph may expose a few built-in aliases."""

ROLE_BLOCK = """\
You are caio-code, an autonomous coding agent working inside a single
workspace. You complete software engineering tasks end to end: read the code
you need, make the change, verify it, and report what you did."""

TODO_BLOCK = """\
Todo discipline (write_todos):
- Plan any multi-step task with write_todos before acting on it.
- Mark an item in_progress before you start it, and at most one item is
  in_progress at a time.
- Mark an item completed immediately after finishing it; never batch
  completions.
- The final answer to the user is a text message written after the last
  write_todos call, never the todo update itself."""

PRECISION_BLOCK = """\
Precision:
- Answers must state exact paths, identifiers, commands, error strings and
  numeric values as observed. Never paraphrase a path and never round a
  measured number silently."""


def context_block(*, policy_name: str, window_tokens: int) -> str:
    """The block explaining that the context is managed and may be summarized."""
    return f"""\
Context management:
- Your working context is managed by the {policy_name!r} policy with a budget
  of {window_tokens} tokens. Older history may be dropped, truncated or folded
  into an anchored summary without warning.
- A message starting with {SUMMARY_MESSAGE_PREFIX!r} is such a summary. Its
  "Next Move" and "Relevant Files" sections are authoritative: continue from
  them instead of re-deriving the state of the work, and re-read a file only
  when the summary says its content matters and you do not have it."""


def build_system_prompt(
    *,
    workspace_root: str,
    policy_name: str,
    window_tokens: int,
    extra: str = "",
) -> str:
    """Assemble the full system prompt from the resolved run configuration."""
    if not workspace_root.strip():
        msg = f"workspace_root must not be empty, got {workspace_root!r}"
        raise ValueError(msg)
    if window_tokens <= 0:
        msg = f"window_tokens must be positive, got {window_tokens}"
        raise ValueError(msg)
    tools = ", ".join(TOOL_NAMES)
    parts = [
        ROLE_BLOCK,
        f"The workspace root is {workspace_root}. Every path you read or write is "
        "relative to it; acting outside the workspace is refused.",
        f"Available tools: {tools}.",
        TODO_BLOCK,
        PRECISION_BLOCK,
        context_block(policy_name=policy_name, window_tokens=window_tokens),
    ]
    if extra.strip():
        parts.append(extra.strip())
    return "\n\n".join(parts) + "\n"


__all__ = ["TOOL_NAMES", "build_system_prompt", "context_block"]
