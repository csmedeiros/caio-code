"""The system prompt builder states the run configuration and the disciplines."""

from __future__ import annotations

import pytest

from caio_code.application.agent.prompt import TOOL_NAMES, build_system_prompt


def test_prompt_includes_policy_window_and_root() -> None:
    prompt = build_system_prompt(
        workspace_root="/tmp/ws",
        policy_name="sliding_window",
        window_tokens=8_000,
    )
    assert "sliding_window" in prompt
    assert "8000 tokens" in prompt
    assert "/tmp/ws" in prompt


def test_prompt_includes_todo_discipline_and_tools() -> None:
    prompt = build_system_prompt(
        workspace_root="/tmp/ws", policy_name="compaction", window_tokens=1_000
    )
    assert "write_todos" in prompt
    assert "in_progress" in prompt
    assert "never batch" in prompt
    for tool in TOOL_NAMES:
        assert tool in prompt


def test_prompt_marks_summary_sections_authoritative() -> None:
    prompt = build_system_prompt(
        workspace_root="/tmp/ws", policy_name="compaction", window_tokens=1_000
    )
    assert "Next Move" in prompt
    assert "Relevant Files" in prompt
    assert "authoritative" in prompt


def test_prompt_appends_extra_block() -> None:
    prompt = build_system_prompt(
        workspace_root="/tmp/ws",
        policy_name="baseline_full_history",
        window_tokens=1_000,
        extra="EXTRA-RULE-42",
    )
    assert "EXTRA-RULE-42" in prompt


def test_prompt_rejects_non_positive_window() -> None:
    with pytest.raises(ValueError, match="window_tokens must be positive, got 0"):
        build_system_prompt(workspace_root="/tmp/ws", policy_name="p", window_tokens=0)


def test_prompt_rejects_empty_root() -> None:
    with pytest.raises(ValueError, match="workspace_root must not be empty"):
        build_system_prompt(workspace_root="  ", policy_name="p", window_tokens=10)
